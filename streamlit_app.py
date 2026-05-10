from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import pickle

import pandas as pd
import requests
import streamlit as st

from tobacco_core.analysis import (
    ParsedWorkbook,
    TIER_COLUMNS,
    build_analysis_dataset,
    build_order_price_check_dataset,
    compare_plan_with_order,
    compute_dual_strategy_summary,
    compute_missing_order_market_prices,
    compute_order_profit,
    compute_profit_recommendation_summary,
    compute_tier_diff,
    compute_tier_plan,
    get_tier_total_qty,
    get_previous_tier,
    parse_orders,
    parse_strategy,
    recommend_profit_plan,
)
from tobacco_core.price_store import load_price_db, merge_order_products, merge_uploaded_prices, save_price_db, upsert_manual_market_prices


LAST_ANALYSIS_STATE_PATH = Path(__file__).resolve().parent / "data" / "last_analysis_state.pkl"


st.set_page_config(page_title="梦回唐朝图文店", layout="wide")

st.markdown(
    """
    <style>
    .block-container {
        max-width: 100%;
        padding-top: 1rem;
        padding-bottom: 1rem;
        padding-left: 2rem;
        padding-right: 2rem;
    }
    h1 {
        font-size: 1.65rem;
        line-height: 1.2;
        margin-bottom: 0.5rem;
    }
    div[data-testid="stMetric"] {
        text-align: center;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def money(value: float) -> str:
    return f"{float(value):,.2f}"


def integer(value: int | float) -> str:
    return f"{int(value):,}"


def signed_diff_html(value: float, is_money: bool = False) -> str:
    negative = value < 0
    color = "#c62828" if negative else "#2e7d32"
    weight = "700"
    display = money(value) if is_money else integer(value)
    return f"<div style='text-align:center;color:{color};font-weight:{weight};font-size:1.15rem'>{display}</div>"


def file_signature(name: str | None, data: bytes | None) -> str | None:
    if data is None:
        return None
    digest = hashlib.md5(data).hexdigest()
    return f"{name or ''}:{len(data)}:{digest}"


def make_uploaded_file(data: bytes | None, name: str | None):
    if data is None:
        return None
    file_obj = BytesIO(data)
    file_obj.name = name
    return file_obj


def load_last_analysis_state() -> None:
    if st.session_state.get("_last_analysis_state_loaded"):
        return
    st.session_state._last_analysis_state_loaded = True
    if not LAST_ANALYSIS_STATE_PATH.exists():
        return
    try:
        with LAST_ANALYSIS_STATE_PATH.open("rb") as handle:
            state = pickle.load(handle)
    except Exception:
        return
    for key in [
        "analysis_started",
        "saved_strategy_file",
        "saved_strategy_name",
        "saved_strategy_signature",
        "saved_order_file",
        "saved_order_name",
        "saved_order_signature",
        "cached_analysis_results",
    ]:
        if key in state:
            st.session_state[key] = state[key]


def save_last_analysis_state() -> None:
    LAST_ANALYSIS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "analysis_started": st.session_state.analysis_started,
        "saved_strategy_file": st.session_state.saved_strategy_file,
        "saved_strategy_name": st.session_state.saved_strategy_name,
        "saved_strategy_signature": st.session_state.saved_strategy_signature,
        "saved_order_file": st.session_state.saved_order_file,
        "saved_order_name": st.session_state.saved_order_name,
        "saved_order_signature": st.session_state.saved_order_signature,
        "cached_analysis_results": st.session_state.get("cached_analysis_results"),
    }
    with LAST_ANALYSIS_STATE_PATH.open("wb") as handle:
        pickle.dump(state, handle)


def stage_uploaded_file(uploaded_file, prefix: str) -> bool:
    data_key = f"pending_{prefix}_file"
    name_key = f"pending_{prefix}_name"
    signature_key = f"pending_{prefix}_signature"
    saved_signature_key = f"saved_{prefix}_signature"
    if uploaded_file is None:
        st.session_state[data_key] = None
        st.session_state[name_key] = None
        st.session_state[signature_key] = None
        return False

    data = uploaded_file.getvalue()
    signature = file_signature(uploaded_file.name, data)
    if signature == st.session_state.get(saved_signature_key):
        st.session_state[data_key] = None
        st.session_state[name_key] = None
        st.session_state[signature_key] = None
        return False

    st.session_state[data_key] = data
    st.session_state[name_key] = uploaded_file.name
    st.session_state[signature_key] = signature
    return True


def get_analysis_file(prefix: str, use_pending: bool):
    if use_pending and st.session_state.get(f"pending_{prefix}_file") is not None:
        return make_uploaded_file(st.session_state.get(f"pending_{prefix}_file"), st.session_state.get(f"pending_{prefix}_name"))
    return make_uploaded_file(st.session_state.get(f"saved_{prefix}_file"), st.session_state.get(f"saved_{prefix}_name"))


def commit_active_analysis_files(use_pending: bool) -> None:
    for prefix in ["strategy", "order"]:
        if use_pending and st.session_state.get(f"pending_{prefix}_file") is not None:
            st.session_state[f"saved_{prefix}_file"] = st.session_state.get(f"pending_{prefix}_file")
            st.session_state[f"saved_{prefix}_name"] = st.session_state.get(f"pending_{prefix}_name")
            st.session_state[f"saved_{prefix}_signature"] = st.session_state.get(f"pending_{prefix}_signature")
            st.session_state[f"pending_{prefix}_file"] = None
            st.session_state[f"pending_{prefix}_name"] = None
            st.session_state[f"pending_{prefix}_signature"] = None
    st.session_state.analysis_started = True
    save_last_analysis_state()


def cache_analysis_results(**results) -> None:
    st.session_state.cached_analysis_results = results
    save_last_analysis_state()


# 初始化 session_state 变量
if "analysis_started" not in st.session_state:
    st.session_state.analysis_started = False

# 持久化上次成功计算使用的文件
if "saved_strategy_file" not in st.session_state:
    st.session_state.saved_strategy_file = None
if "saved_strategy_name" not in st.session_state:
    st.session_state.saved_strategy_name = None
if "saved_strategy_signature" not in st.session_state:
    st.session_state.saved_strategy_signature = None
if "saved_order_file" not in st.session_state:
    st.session_state.saved_order_file = None
if "saved_order_name" not in st.session_state:
    st.session_state.saved_order_name = None
if "saved_order_signature" not in st.session_state:
    st.session_state.saved_order_signature = None
if "cached_analysis_results" not in st.session_state:
    st.session_state.cached_analysis_results = None
for prefix in ["strategy", "order"]:
    for suffix in ["file", "name", "signature"]:
        key = f"pending_{prefix}_{suffix}"
        if key not in st.session_state:
            st.session_state[key] = None

load_last_analysis_state()

st.title("梦回唐朝图文店")

db_prices = load_price_db()

st.subheader("1. 上传分析文件")
col1, col2 = st.columns(2)
with col1:
    uploaded_strategy_file = st.file_uploader("订货量 / 投放表", type=["xlsx"], key="strategy_file")
    strategy_changed = stage_uploaded_file(uploaded_strategy_file, "strategy")
with col2:
    uploaded_order_file = st.file_uploader("订单明细（可选）", type=["xlsx"], key="order_file")
    order_changed = stage_uploaded_file(uploaded_order_file, "order")

has_pending_upload = strategy_changed or order_changed

def fetch_market_prices_from_api() -> pd.DataFrame:
    try:
        response = requests.get("http://localhost:9527/api/market-price/all", timeout=10)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            data = data.get("data", [])
        if not isinstance(data, list) or len(data) == 0:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        rename_map = {
            "product_name": "商品名称",
            "name": "商品名称",
            "suggested_price": "建议零售价",
            "retail_price": "建议零售价",
            "price": "批发价",
            "purchase_price": "批发价",
            "market_price": "当期找货价格",
            "product_code": "条码",
            "barcode": "条码",
            "box_code": "盒码",
        }
        df = df.rename(columns={key: value for key, value in rename_map.items() if key in df.columns})
        required_cols = ["商品名称", "建议零售价", "批发价", "当期找货价格", "盒码", "条码"]
        if "商品名称" not in df.columns:
            return pd.DataFrame()

        for column in required_cols:
            if column not in df.columns:
                df[column] = pd.NA
        for column in ["建议零售价", "批发价", "当期找货价格"]:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        for column in ["盒码", "条码"]:
            df[column] = df[column].astype("string").str.replace(r"\.0$", "", regex=True).str.strip()

        df = df[df["商品名称"].notna()].copy()
        df["商品名称"] = df["商品名称"].astype(str).str.strip()
        df = df[df["商品名称"].ne("")]
        return (
            df[required_cols]
            .drop_duplicates(subset=["商品名称", "条码"], keep="last")
            .reset_index(drop=True)
        )
    except Exception as e:
        st.warning(f"从 API 获取行情价格失败: {e}")
        return pd.DataFrame()

col1, col2 = st.columns([3, 1])
with col1:
    calculation_requested = st.button("开始计算", type="primary", use_container_width=True)
with col2:
    clear_cache = st.button("清除数据", use_container_width=True)

use_pending_files = calculation_requested and has_pending_upload

if clear_cache:
    st.session_state.analysis_started = False
    st.session_state.saved_strategy_file = None
    st.session_state.saved_strategy_name = None
    st.session_state.saved_strategy_signature = None
    st.session_state.saved_order_file = None
    st.session_state.saved_order_name = None
    st.session_state.saved_order_signature = None
    st.session_state.cached_analysis_results = None
    st.session_state.pending_strategy_file = None
    st.session_state.pending_strategy_name = None
    st.session_state.pending_strategy_signature = None
    st.session_state.pending_order_file = None
    st.session_state.pending_order_name = None
    st.session_state.pending_order_signature = None
    if LAST_ANALYSIS_STATE_PATH.exists():
        LAST_ANALYSIS_STATE_PATH.unlink()
    st.rerun()

if calculation_requested:
    st.session_state.analysis_started = True

if not st.session_state.analysis_started:
    st.info("文件上传完成后，点击“开始计算”再执行分析。")
    st.stop()

if has_pending_upload and not calculation_requested:
    st.info("已选择新的投放表或订单明细。当前仍展示上次计算结果，点击“开始计算”后会更新并保存新结果。")

strategy_file = get_analysis_file("strategy", use_pending_files)
order_file = get_analysis_file("order", use_pending_files)

cached_analysis_results = st.session_state.get("cached_analysis_results")
use_cached_analysis_results = not calculation_requested and cached_analysis_results is not None

if use_cached_analysis_results:
    parsed = cached_analysis_results["parsed"]
    analysis_data = cached_analysis_results["analysis_data"]
    missing_order_market_prices = cached_analysis_results["missing_order_market_prices"]
    has_order = cached_analysis_results["has_order"]
    has_strategy = cached_analysis_results["has_strategy"]
    order_profit = cached_analysis_results["order_profit"]
    order_total_qty = cached_analysis_results["order_total_qty"]
    order_total_cost = cached_analysis_results["order_total_cost"]
    order_total_profit = cached_analysis_results["order_total_profit"]
    current_tier = cached_analysis_results["current_tier"]
    tier_reason = cached_analysis_results["tier_reason"]
    compare_tier = cached_analysis_results["compare_tier"]
    current_cost_plan = cached_analysis_results["current_cost_plan"]
    current_profit_plan = cached_analysis_results["current_profit_plan"]
    compare_cost_plan = cached_analysis_results["compare_cost_plan"]
    dual_summary = cached_analysis_results["dual_summary"]
    profit_recommendation_summary = cached_analysis_results["profit_recommendation_summary"]
    db_prices = cached_analysis_results["db_prices"]
else:
    if calculation_requested:
        uploaded_prices = fetch_market_prices_from_api()
        if not uploaded_prices.empty:
            db_prices = merge_uploaded_prices(db_prices, uploaded_prices)
            save_price_db(db_prices)
            st.success(f"已从 API 更新行情价格库，本次写入 {len(uploaded_prices)} 条价格记录。")

    if db_prices.empty:
        st.error("当前行情价格库为空，无法引用历史批发价，请检查本地 API 服务是否正常运行。")
        st.stop()

    try:
        # 初始化变量
        strategy_items = pd.DataFrame()
        segment_limits = pd.DataFrame()
        tier_totals = pd.DataFrame()
        empty_order = pd.DataFrame(columns=["商品名称", "批发价", "订单量"])
    
        # 如果有投放表，解析投放表
        if strategy_file is not None:
            strategy_items, segment_limits, tier_totals = parse_strategy(strategy_file)
    
        # 如果有订单表，解析订单表
        if order_file is None:
            orders = empty_order
        else:
            orders = parse_orders(order_file)
            db_prices = merge_order_products(db_prices, orders)
            save_price_db(db_prices)
    
        # 创建parsed对象
        parsed = ParsedWorkbook(
            orders=orders,
            prices=db_prices.copy(),
            strategy_items=strategy_items,
            segment_limits=segment_limits,
            tier_totals=tier_totals,
        )
        analysis_data = build_analysis_dataset(parsed)
    except Exception as exc:
        st.error(f"订单或订货量文件解析失败：{exc}")
        st.stop()


    missing_order_market_prices = pd.DataFrame()

    has_order = order_file is not None
    has_strategy = strategy_file is not None

    # 如果有订单表，计算订单盈亏
    order_profit = pd.DataFrame()
    if has_order:
        try:
            # 直接用订单表构建一个简单的分析数据，确保订单盈亏分析能正常工作
            if not has_strategy:
                # 如果没有投放表，直接用订单表和价格表构建数据
                order_analysis_data = parsed.orders.copy()
                # 合并价格信息
                if "商品名称" in order_analysis_data.columns and "商品名称" in db_prices.columns:
                    price_cols = ["商品名称", "批发价", "建议零售价", "当期找货价格"]
                    existing_price_cols = [col for col in price_cols if col in db_prices.columns]
                    order_analysis_data = order_analysis_data.merge(
                        db_prices[existing_price_cols],
                        on="商品名称",
                        how="left",
                        suffixes=("", "_price")
                    )
                    # 使用价格库的批发价
                    if "批发价_price" in order_analysis_data.columns:
                        order_analysis_data["批发价"] = order_analysis_data["批发价_price"].fillna(order_analysis_data.get("批发价"))
                    # 使用价格库的当期找货价格
                    if "当期找货价格_price" in order_analysis_data.columns:
                        order_analysis_data["当期找货价格"] = order_analysis_data["当期找货价格_price"].fillna(order_analysis_data.get("当期找货价格"))
            
                # 确保有必要的列
                if "价位段" not in order_analysis_data.columns:
                    order_analysis_data["价位段"] = ""
                if "有效销售价" not in order_analysis_data.columns:
                    order_analysis_data["有效销售价"] = order_analysis_data.get("当期找货价格", pd.Series()).fillna(order_analysis_data.get("批发价"))
                if "单条毛利" not in order_analysis_data.columns:
                    order_analysis_data["单条毛利"] = order_analysis_data["有效销售价"] - order_analysis_data["批发价"]
            
                # 计算订单盈亏
                temp_order_profit = order_analysis_data[order_analysis_data["订单量"] > 0].copy()
                temp_order_profit["订单成本"] = temp_order_profit["订单量"] * temp_order_profit["批发价"]
                temp_order_profit["订单估值"] = temp_order_profit["订单量"] * temp_order_profit["有效销售价"]
                temp_order_profit["订单盈亏"] = temp_order_profit["订单量"] * temp_order_profit["单条毛利"]
                order_profit = temp_order_profit.sort_values(["订单盈亏", "订单成本"], ascending=[False, False]).reset_index(drop=True)
            else:
                # 如果有投放表，使用原来的方法
                order_profit = compute_order_profit(analysis_data)
        except Exception as e:
            st.warning(f"计算订单盈亏时出错：{e}，将使用简化方法计算")
            # 简化方法
            if "订单量" in parsed.orders.columns and "批发价" in parsed.orders.columns:
                temp = parsed.orders[parsed.orders["订单量"] > 0].copy()
                temp["订单成本"] = temp["订单量"] * temp["批发价"]
                order_profit = temp

    if has_order:
        order_price_check = build_order_price_check_dataset(parsed.orders, db_prices)
        missing_order_market_prices = compute_missing_order_market_prices(order_price_check)

    order_total_qty = int(order_profit["订单量"].sum()) if not order_profit.empty and "订单量" in order_profit.columns else 0
    order_total_cost = float(order_profit["订单成本"].sum()) if not order_profit.empty and "订单成本" in order_profit.columns else 0.0
    order_total_profit = float(order_profit["订单盈亏"].sum()) if not order_profit.empty and "订单盈亏" in order_profit.columns else 0.0
    current_tier = "三十档"
    tier_reason = "按你的使用口径固定为三十档订单" if has_order else "未上传订单，按默认三十档展示可计算结果"
    compare_tier = get_previous_tier(current_tier) if has_strategy else None

    # 只有有投放表时才计算满订计划
    current_cost_plan = None
    current_profit_plan = None
    compare_cost_plan = None
    dual_summary = pd.DataFrame()
    profit_recommendation_summary = pd.DataFrame()

    if has_strategy:
        current_cost_plan = compute_tier_plan(analysis_data, parsed.segment_limits, current_tier, "cost", get_tier_total_qty(parsed.tier_totals, current_tier))
        current_profit_plan = compute_tier_plan(analysis_data, parsed.segment_limits, current_tier, "profit", get_tier_total_qty(parsed.tier_totals, current_tier))
        compare_cost_plan = compute_tier_plan(analysis_data, parsed.segment_limits, compare_tier, "cost", get_tier_total_qty(parsed.tier_totals, compare_tier)) if compare_tier else None
        dual_summary = compute_dual_strategy_summary(analysis_data, parsed.segment_limits, parsed.tier_totals)
        profit_recommendation_summary = compute_profit_recommendation_summary(analysis_data, parsed.segment_limits, parsed.tier_totals)


    if calculation_requested:
        commit_active_analysis_files(use_pending_files)
    cache_analysis_results(
        parsed=parsed,
        analysis_data=analysis_data,
        missing_order_market_prices=missing_order_market_prices,
        has_order=has_order,
        has_strategy=has_strategy,
        order_profit=order_profit,
        order_total_qty=order_total_qty,
        order_total_cost=order_total_cost,
        order_total_profit=order_total_profit,
        current_tier=current_tier,
        tier_reason=tier_reason,
        compare_tier=compare_tier,
        current_cost_plan=current_cost_plan,
        current_profit_plan=current_profit_plan,
        compare_cost_plan=compare_cost_plan,
        dual_summary=dual_summary,
        profit_recommendation_summary=profit_recommendation_summary,
        db_prices=db_prices,
    )

st.subheader("识别结果")
if has_order:
    meta = st.columns(5)
    meta[0].metric("订单总条数", integer(order_total_qty))
    meta[1].metric("推断当前档位", current_tier)
    meta[2].metric("对比档位", compare_tier or "无")
    meta[3].metric("订单总成本", money(order_total_cost))
    meta[4].metric("订单总盈亏", money(order_total_profit))
else:
    meta = st.columns(3)
    meta[0].metric("推断当前档位", current_tier)
    meta[1].metric("对比档位", compare_tier or "无")
st.caption(f"档位推断口径：{tier_reason}。投放表中标记为二次自选或控制量的行不会作为商品参与订购、满订和推荐。若本次未上传行情表，则直接使用本地价格库中的批发价/找货价；找货价缺失时回退批发价。")

st.divider()
st.subheader("2. 订单与下一档位最高最贵满订差异")
if not has_order:
    st.info("未上传订单，已跳过订单差异对比。")
elif not has_strategy:
    st.info("未上传投放表，已跳过订单差异对比。")
elif compare_cost_plan is None:
    st.info("当前档位已经没有下一档位可比较。")
else:
    amount_diff = order_total_cost - compare_cost_plan.total_cost
    qty_diff = order_total_qty - compare_cost_plan.total_qty
    cols = st.columns(4)
    cols[0].metric("当前订单档位", current_tier)
    cols[1].metric("对比档位", compare_tier)
    cols[2].metric(f"{compare_tier}最高最贵满订金额", money(compare_cost_plan.total_cost))
    with cols[3]:
        st.markdown("<div style='text-align:center'>与当前订单金额差</div>", unsafe_allow_html=True)
        st.markdown(signed_diff_html(amount_diff, is_money=True), unsafe_allow_html=True)
    cols2 = st.columns(4)
    cols2[0].metric(f"{compare_tier}最高最贵满订条数", integer(compare_cost_plan.total_qty))
    with cols2[1]:
        st.markdown("<div style='text-align:center'>与当前订单条数差</div>", unsafe_allow_html=True)
        st.markdown(signed_diff_html(qty_diff, is_money=False), unsafe_allow_html=True)
    cols2[2].metric(f"{compare_tier}最高最贵满订盈亏", money(compare_cost_plan.total_profit))
    cols2[3].metric("未满足段上限", integer(compare_cost_plan.unmet_segment_limit))

st.divider()
st.subheader("3. 订单盈亏分析")
if not has_order:
    st.info("未上传订单，已跳过订单盈亏分析。")
elif order_profit.empty:
    st.info("订单数据为空，无法显示订单盈亏分析。")
else:
    cards = st.columns(4)
    cards[0].metric("订单商品数", integer(len(order_profit)))
    cards[1].metric("订单总成本", money(order_total_cost))
    # 只在有订单估值列时显示
    order_total_value = 0.0
    if "订单估值" in order_profit.columns:
        order_total_value = float(order_profit["订单估值"].sum())
    cards[2].metric("订单总估值", money(order_total_value))
    cards[3].metric("订单总盈亏", money(order_total_profit))
    
    # 只显示存在的列
    display_columns = []
    for col in ["价位段", "商品名称", "订单量", "批发价", "当期找货价格", "单条毛利", "订单成本", "订单盈亏"]:
        if col in order_profit.columns:
            display_columns.append(col)
    
    if display_columns:
        st.dataframe(
            order_profit[display_columns],
            use_container_width=True,
            hide_index=True,
        )
    if not missing_order_market_prices.empty:
        st.markdown("**以下订单商品已自动加入商品库，但还没有行情价格，请补录后保存**")
        order_editable = missing_order_market_prices.copy()
        order_editable = order_editable[order_editable["商品名称"].astype(str).str.strip().ne("合计")].copy()
        order_editable["当期找货价格"] = order_editable["当期找货价格"].astype("float64")
        if order_editable.empty:
            st.info("缺少行情价格的订单商品里只有“合计”行，已自动排除。")
        else:
            with st.form("missing_order_market_prices_form"):
                order_edited = st.data_editor(
                    order_editable,
                    use_container_width=True,
                    hide_index=True,
                    key="missing_order_market_prices_editor",
                )
                save_order_prices = st.form_submit_button("保存订单缺失行情价格", type="primary")
            if save_order_prices:
                manual = order_edited.copy()
                manual = manual[manual["商品名称"].astype(str).str.strip().ne("合计")].copy()
                manual = manual[manual["当期找货价格"].notna()].copy()
                if manual.empty:
                    st.warning("还没有填写可保存的订单行情价格。")
                else:
                    manual["批发价"] = pd.to_numeric(manual.get("批发价"), errors="coerce")
                    manual["建议零售价"] = pd.to_numeric(manual.get("建议零售价"), errors="coerce")
                    updated_db = upsert_manual_market_prices(db_prices, manual)
                    save_price_db(updated_db)
                    st.success(f"已把 {len(manual)} 条订单商品行情价格写入价格库。刷新后会按新价格重新计算。")

st.divider()
st.subheader("4. 本期档位最高满订汇总")
if not has_strategy:
    st.info("未上传投放表，已跳过满订汇总。")
else:
    sum_cols = st.columns(4)
    sum_cols[0].metric(f"{current_tier}最贵满订金额", money(current_cost_plan.total_cost))
    sum_cols[1].metric(f"{current_tier}利润优先满订金额", money(current_profit_plan.total_cost))
    sum_cols[2].metric(f"{current_tier}最贵满订条数", integer(current_cost_plan.total_qty))
    sum_cols[3].metric(f"{current_tier}利润优先满订盈亏", money(current_profit_plan.total_profit))
    st.dataframe(dual_summary, use_container_width=True, hide_index=True)

    selected_detail_tier = st.selectbox("查看满订明细档位", TIER_COLUMNS, index=TIER_COLUMNS.index("三十档"), key="selected_detail_tier")
    selected_cost_plan = compute_tier_plan(analysis_data, parsed.segment_limits, selected_detail_tier, "cost", get_tier_total_qty(parsed.tier_totals, selected_detail_tier))
    selected_profit_plan = compute_tier_plan(analysis_data, parsed.segment_limits, selected_detail_tier, "profit", get_tier_total_qty(parsed.tier_totals, selected_detail_tier))

    st.markdown(f"**{selected_detail_tier}最高最贵满订明细**")
    st.dataframe(
        selected_cost_plan.line_items[["来源", "价位段", "商品名称", "档位可订量", "计划量", "批发价", "计划成本", "计划盈亏"]],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown(f"**{selected_detail_tier}利润优先满订明细**")
    st.dataframe(
        selected_profit_plan.line_items[["来源", "价位段", "商品名称", "档位可订量", "计划量", "批发价", "计划成本", "计划盈亏"]],
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("5. 档位差异烟对比")
if not has_strategy:
    st.info("未上传投放表，已跳过档位差异对比。")
else:
    selector_cols = st.columns(2)
    default_high = current_tier
    default_low = compare_tier or current_tier
    selected_high = selector_cols[0].selectbox("高档位", TIER_COLUMNS, index=TIER_COLUMNS.index(default_high))
    selected_low = selector_cols[1].selectbox("低档位", TIER_COLUMNS, index=TIER_COLUMNS.index(default_low))
    if TIER_COLUMNS.index(selected_high) >= TIER_COLUMNS.index(selected_low):
        st.warning("高档位必须比低档位更高。")
    else:
        tier_diff = compute_tier_diff(analysis_data, selected_high, selected_low)
        
        # 展示各段位上限对比
        st.markdown(f"**{selected_high} 与 {selected_low} 各段位上限对比**")
        
        # 从segment_limits获取各段位上限
        if not parsed.segment_limits.empty and selected_high in parsed.segment_limits.columns and selected_low in parsed.segment_limits.columns:
            # 获取两个档位的段位上限数据
            segment_limits_comparison = parsed.segment_limits[["价位段", selected_high, selected_low]].copy()
            
            # 确保数值列是数值类型
            for col in [selected_high, selected_low]:
                segment_limits_comparison[col] = pd.to_numeric(segment_limits_comparison[col], errors='coerce').fillna(0)
            
            segment_limits_comparison = segment_limits_comparison.rename(
                columns={selected_high: f"{selected_high}上限", selected_low: f"{selected_low}上限"}
            )
            
            # 计算差值
            segment_limits_comparison[f"上限差值({selected_high}-{selected_low})"] = (
                segment_limits_comparison[f"{selected_high}上限"] - segment_limits_comparison[f"{selected_low}上限"]
            )
            
            # 只显示有差异的行
            segment_limits_comparison = segment_limits_comparison[
                segment_limits_comparison[f"上限差值({selected_high}-{selected_low})"] != 0
            ]
            
            st.dataframe(segment_limits_comparison, use_container_width=True, hide_index=True)
        else:
            st.info("无法获取段位上限数据进行对比。")
        
        # 展示差异烟
        st.markdown(f"**{selected_high} 与 {selected_low} 差异烟对比**")
        diff_cols = st.columns(2)
        diff_cols[0].metric("差异品种数", integer(len(tier_diff)))
        diff_cols[1].metric("差异总条数", integer(int(tier_diff["新增量"].sum()) if not tier_diff.empty else 0))
        
        if not tier_diff.empty:
            st.dataframe(
                tier_diff[["价位段", "商品名称", "低档位可订量", "高档位可订量", "新增量"]],
                use_container_width=True,
                hide_index=True,
            )

st.divider()
st.subheader("6. 各档位最高利润订购推荐")
if not has_strategy:
    st.info("未上传投放表，已跳过利润推荐。")
else:
    recommend_tier = st.selectbox("选择推荐档位", TIER_COLUMNS, index=TIER_COLUMNS.index("三十档"), key="recommend_tier")
    recommend_compare_tier = get_previous_tier(recommend_tier)
    if recommend_compare_tier is None:
        st.info(f"{recommend_tier} 已经没有更低一档可作为对比，暂时无法生成推荐。")
    else:
        st.caption(f"先按 {recommend_tier} 利润优先满订生成方案，再从单条毛利最低的商品开始逐条删减；每删一条都校验一次，直到再删就会导致总条数或总金额不再高于 {recommend_compare_tier} 最高最贵满订。")
        profit_recommendation = recommend_profit_plan(analysis_data, parsed.segment_limits, recommend_tier, parsed.tier_totals)
        compare_cost_recommendation = compute_tier_plan(analysis_data, parsed.segment_limits, recommend_compare_tier, "cost", get_tier_total_qty(parsed.tier_totals, recommend_compare_tier))
        if profit_recommendation is None:
            st.warning(f"没有找到同时满足“总条数和总金额都高于 {recommend_compare_tier} 最高最贵满订”的 {recommend_tier} 利润推荐方案。")
        else:
            rec_cols = st.columns(4)
            rec_cols[0].metric("推荐总条数", integer(profit_recommendation.total_qty))
            rec_cols[1].metric("推荐总金额", money(profit_recommendation.total_cost))
            rec_cols[2].metric("推荐总盈亏", money(profit_recommendation.total_profit))
            rec_cols[3].metric(f"较{recommend_compare_tier}最贵满订多出金额", money(profit_recommendation.total_cost - compare_cost_recommendation.total_cost))
            st.dataframe(
                profit_recommendation.line_items[["来源", "价位段", "商品名称", "档位可订量", "计划量", "批发价", "计划成本", "计划盈亏"]],
                use_container_width=True,
                hide_index=True,
            )
            if has_order and recommend_tier == "三十档":
                order_context = (
                    analysis_data[["商品名称", "价位段", "批发价"]]
                    .dropna(subset=["商品名称"])
                    .drop_duplicates(subset=["商品名称"], keep="first")
                )
                order_compare = (
                    profit_recommendation.line_items[["商品名称", "价位段", "计划量", "批发价"]]
                    .merge(
                        parsed.orders[["商品名称", "订单量"]],
                        on="商品名称",
                        how="outer",
                    )
                )
                order_compare = order_compare.merge(order_context, on="商品名称", how="left", suffixes=("", "_分析"))
                order_compare["价位段"] = order_compare["价位段"].fillna(order_compare["价位段_分析"])
                order_compare["批发价"] = pd.to_numeric(order_compare["批发价"], errors="coerce").fillna(pd.to_numeric(order_compare["批发价_分析"], errors="coerce"))
                order_compare["计划量"] = pd.to_numeric(order_compare["计划量"], errors="coerce").fillna(0).astype(int)
                order_compare["订单量"] = pd.to_numeric(order_compare["订单量"], errors="coerce").fillna(0).astype(int)
                order_compare["调整量"] = order_compare["计划量"] - order_compare["订单量"]
                order_compare = order_compare[order_compare["调整量"] != 0].copy()
                if not order_compare.empty:
                    order_compare["调整动作"] = order_compare["调整量"].apply(lambda x: "增加" if x > 0 else "减少")
                    order_compare["调整条数"] = order_compare["调整量"].abs()
                    order_compare["调整金额"] = order_compare["调整量"] * pd.to_numeric(order_compare["批发价"], errors="coerce").fillna(0)
                    segment_sort_order = {"1-3段": 1, "4-5段": 2, "6段": 3, "8-9段": 4, "10段": 5, "11段": 6, "12段": 7, "13段": 8, "按档位投放": 9}
                    order_compare["分段排序"] = order_compare["价位段"].map(segment_sort_order).fillna(99)
                    order_compare = order_compare.sort_values(["分段排序", "价位段", "调整动作", "调整条数", "商品名称"], ascending=[True, True, True, False, True]).reset_index(drop=True)
                    st.markdown("**与当前订单相比，建议这样修改**")
                    st.dataframe(
                        order_compare[["调整动作", "商品名称", "价位段", "订单量", "计划量", "调整条数", "批发价", "调整金额"]],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.success("当前订单已经和这套推荐方案一致，不需要修改。")
if has_strategy:
    st.markdown("**各档位最高利润推荐汇总**")
    
    # 合并dual_summary和profit_recommendation_summary，包含最贵满订相关列
    merged_profit_summary = dual_summary.merge(
        profit_recommendation_summary,
        on="档位",
        how="outer",
        suffixes=("_满订", "_推荐")
    )
    
    # 选择需要的列并重新排列
    profit_display_columns = [
        "档位",
        "最贵满订条数",
        "最贵满订金额",
        "最贵满订盈亏",
        "利润优先满订条数",
        "利润优先满订金额",
        "利润优先满订盈亏",
        "推荐条数",
        "推荐金额",
        "推荐盈亏",
        "较利润优先满订条数差",
        "较利润优先满订金额差",
        "较利润优先满订盈亏差",
        "较下一档最贵满订多条数",
        "较下一档最贵满订多金额"
    ]
    
    # 只保留存在的列
    profit_existing_columns = [col for col in profit_display_columns if col in merged_profit_summary.columns]
    profit_summary_display = merged_profit_summary[profit_existing_columns].copy()
    
    # 按三十档然后递减排列
    profit_summary_display["档位序号"] = profit_summary_display["档位"].apply(lambda x: TIER_COLUMNS.index(x) if x in TIER_COLUMNS else 999)
    profit_summary_display = profit_summary_display.sort_values("档位序号", ascending=True).drop(columns=["档位序号"])
    profit_format_map = {}
    for col in [col for col in profit_summary_display.columns if col != "档位"]:
        profit_summary_display[col] = pd.to_numeric(profit_summary_display[col], errors="coerce").fillna(0)
        if "条数" in col:
            profit_summary_display[col] = profit_summary_display[col].astype(int)
            profit_format_map[col] = "{:.0f}"
        else:
            profit_summary_display[col] = profit_summary_display[col].round(2)
            profit_format_map[col] = "{:.2f}"
    
    # 创建样式器
    profit_styler = profit_summary_display.style
    
    # 获取列名
    profit_cols = profit_summary_display.columns.tolist()
    
    # 找到各部分的起始列
    profit_profit_cols_start = profit_cols.index("推荐条数") if "推荐条数" in profit_cols else len(profit_cols)
    profit_diff_cols_start = profit_cols.index("较利润优先满订条数差") if "较利润优先满订条数差" in profit_cols else len(profit_cols)
    
    # 设置样式
    for col in profit_cols:
        col_idx = profit_cols.index(col)
        if col_idx >= profit_profit_cols_start and col_idx < profit_diff_cols_start:
            # 推荐部分使用浅绿色
            profit_styler = profit_styler.set_properties(subset=[col], **{'background-color': '#d4edda'})
        elif col_idx >= profit_diff_cols_start:
            # 对比部分使用浅青色
            profit_styler = profit_styler.set_properties(subset=[col], **{'background-color': '#d1ecf1'})
        else:
            # 满订部分使用浅白色
            profit_styler = profit_styler.set_properties(subset=[col], **{'background-color': '#ffffff'})
    
    # 设置表头样式
    profit_styler = profit_styler.set_table_styles([
        {'selector': 'th', 'props': [('background-color', '#f8f9fa'), ('font-weight', 'bold')]},
    ])
    
    # 格式化数值列
    profit_styler = profit_styler.format(profit_format_map, na_rep="None")
    
    st.dataframe(
        profit_styler,
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("7. 各档位升档打满订单分析")

if not has_strategy:
    st.info("未上传投放表，已跳过升档打满订单分析。")
else:
    if not dual_summary.empty and not profit_recommendation_summary.empty:
        merged_summary = dual_summary.merge(
            profit_recommendation_summary,
            on="档位",
            how="outer",
            suffixes=("_满订", "_推荐")
        )

        def merged_column(name: str) -> pd.Series:
            for candidate in [f"{name}_满订", name, f"{name}_推荐"]:
                if candidate in merged_summary.columns:
                    return merged_summary[candidate]
            return pd.Series(pd.NA, index=merged_summary.index)

        final_summary = pd.DataFrame(
            {
                "档位": merged_summary["档位"],
                "最贵满订条数": merged_column("最贵满订条数"),
                "最贵满订金额": merged_column("最贵满订金额"),
                "最贵满订盈亏": merged_column("最贵满订盈亏"),
                "利润优先满订金额": merged_column("利润优先满订金额"),
                "利润优先满订盈亏": merged_column("利润优先满订盈亏"),
                "推荐条数": merged_column("推荐条数"),
                "推荐金额": merged_column("推荐金额"),
                "推荐盈亏": merged_column("推荐盈亏"),
            }
        )
        final_summary["档位序号"] = final_summary["档位"].apply(lambda x: TIER_COLUMNS.index(x) if x in TIER_COLUMNS else 999)
        final_summary = final_summary.sort_values("档位序号", ascending=True).drop(columns=["档位序号"])

        numeric_columns = [col for col in final_summary.columns if col != "档位"]
        for col in numeric_columns:
            final_summary[col] = pd.to_numeric(final_summary[col], errors="coerce")
            final_summary[col] = final_summary[col].mask(final_summary[col].abs() < 0.005, 0)

        final_summary.columns = pd.MultiIndex.from_tuples(
            [
                ("", "档位"),
                ("升档", "最贵满订条数"),
                ("升档", "最贵满订金额"),
                ("升档", "最贵满订盈亏"),
                ("满订", "利润优先满订金额"),
                ("满订", "利润优先满订盈亏"),
                ("保档", "推荐条数"),
                ("保档", "推荐金额"),
                ("保档", "推荐盈亏"),
            ]
        )

        styler = final_summary.style
        upgrade_columns = [("升档", "最贵满订条数"), ("升档", "最贵满订金额"), ("升档", "最贵满订盈亏")]
        full_columns = [("满订", "利润优先满订金额"), ("满订", "利润优先满订盈亏")]
        keep_columns = [("保档", "推荐条数"), ("保档", "推荐金额"), ("保档", "推荐盈亏")]

        def style_summary_cells(values: pd.DataFrame) -> pd.DataFrame:
            styles = pd.DataFrame("", index=values.index, columns=values.columns)
            for col in upgrade_columns:
                if col in values.columns:
                    styles[col] = "background-color: #ffffff"
            for col in full_columns:
                if col in values.columns:
                    styles[col] = "background-color: #dcebf7"
            for col in keep_columns:
                if col in values.columns:
                    styles[col] = "background-color: #c6efce"
            loss_col = ("升档", "最贵满订盈亏")
            if loss_col in values.columns:
                styles.loc[values[loss_col] < 0, loss_col] += "; color: red; font-weight: 700"
            for bold_col in [("满订", "利润优先满订盈亏"), ("保档", "推荐盈亏")]:
                if bold_col in values.columns:
                    styles.loc[values[bold_col].notna(), bold_col] += "; font-weight: 700"
            return styles

        styler = styler.apply(style_summary_cells, axis=None)

        styler = styler.set_table_styles([
            {"selector": "th", "props": [("background-color", "#f8f9fa"), ("font-weight", "bold"), ("text-align", "center"), ("border", "1px solid #111")]},
            {"selector": "td", "props": [("border", "1px solid #111"), ("text-align", "right")]},
        ])

        styler = styler.format(
            {
                ("升档", "最贵满订条数"): "{:.0f}",
                ("升档", "最贵满订金额"): "{:.2f}",
                ("升档", "最贵满订盈亏"): "{:.2f}",
                ("满订", "利润优先满订金额"): "{:.2f}",
                ("满订", "利润优先满订盈亏"): "{:.2f}",
                ("保档", "推荐条数"): "{:.0f}",
                ("保档", "推荐金额"): "{:.2f}",
                ("保档", "推荐盈亏"): "{:.2f}",
            },
            na_rep="",
        )

        st.dataframe(styler, use_container_width=True, hide_index=True)
        
        # 导出为Excel
        output = BytesIO()
        final_summary.to_excel(output, index=False, sheet_name='升档打满订单分析')
        output.seek(0)
        st.download_button(
            label="导出为Excel",
            data=output,
            file_name='各档位升档打满订单分析.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            use_container_width=True,
        )
    else:
        st.info("当前没有可展示的升档、满订、保档汇总。")

st.divider()
st.subheader("8. 本期投放规则展示")

if not has_strategy:
    st.info("未上传投放表，已跳过投放规则展示。")
else:
    # 展示投放表信息
    if not parsed.strategy_items.empty:
        # 显示当前选中档位的投放规则
        show_rule_tier = st.selectbox("选择查看投放规则的档位", TIER_COLUMNS, index=TIER_COLUMNS.index("三十档"), key="show_rule_tier")
        
        # 获取该档位的投放数据
        tier_rule_data = parsed.strategy_items[["价位段", "商品名称", show_rule_tier]].copy()
        tier_rule_data = tier_rule_data.rename(columns={show_rule_tier: "可订量"})
        tier_rule_data = tier_rule_data[tier_rule_data["可订量"] > 0].copy()
        
        # 计算每个段位的商品数量和总条数
        segment_summary = tier_rule_data.groupby("价位段", as_index=False).agg(
            商品数量=("商品名称", "count"),
            总条数=("可订量", "sum")
        )
        
        # 获取段位上限
        if not parsed.segment_limits.empty:
            segment_limits_for_tier = parsed.segment_limits[["价位段", show_rule_tier]].copy()
            segment_limits_for_tier = segment_limits_for_tier.rename(columns={show_rule_tier: "段位上限"})
            segment_summary = segment_summary.merge(segment_limits_for_tier, on="价位段", how="left")
        
        # 展示段位汇总信息（包括按档位投放）
        st.markdown(f"**{show_rule_tier} 段位汇总**")
        
        # 计算总条数：段位上限总和 + 按档位投放数量
        if not parsed.segment_limits.empty:
            # 获取非按档位投放的段位上限总和
            regular_segment_limits = segment_limits_for_tier[~segment_limits_for_tier["价位段"].isin(["按档位投放"])].copy()
            limits_total = regular_segment_limits["段位上限"].sum()
            
            # 获取按档位投放的数量
            non_segment_items = tier_rule_data[tier_rule_data["价位段"].isin(["按档位投放"])].copy()
            non_segment_total = non_segment_items["可订量"].sum() if not non_segment_items.empty else 0
            
            # 总条数 = 段位上限总和 + 按档位投放数量
            total_items = int(limits_total) + int(non_segment_total)
        else:
            total_items = tier_rule_data["可订量"].sum()
        
        st.dataframe(segment_summary, use_container_width=True, hide_index=True)
        
        # 展示总条数
        st.metric(f"{show_rule_tier} 总可订条数", integer(total_items))
        
        # 展示所有档位的投放规则对比（包括按档位投放的明细）
        st.markdown("**各档位投放规则对比**")
        
        # 使用原始数据展示各档位的投放规则对比
        # 先展示每个商品在各档位的可订量
        all_tiers_detail = parsed.strategy_items.copy()
        
        # 按三十档可订量递减排序
        if "三十档" in all_tiers_detail.columns:
            all_tiers_detail = all_tiers_detail.sort_values("三十档", ascending=False).reset_index(drop=True)
        
        # 选择要展示的列
        display_columns = ["价位段", "商品名称"] + [tier for tier in TIER_COLUMNS if tier in all_tiers_detail.columns]
        all_tiers_detail = all_tiers_detail[display_columns].copy()
        
        # 过滤掉可订量全为0的商品
        if len(TIER_COLUMNS) > 0:
            mask = all_tiers_detail[TIER_COLUMNS].sum(axis=1) > 0
            all_tiers_detail = all_tiers_detail[mask].copy()
        
        st.dataframe(all_tiers_detail, use_container_width=True, hide_index=True)
