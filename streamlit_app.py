from __future__ import annotations

import pandas as pd
import streamlit as st

from tobacco_core.analysis import (
    ParsedWorkbook,
    TIER_COLUMNS,
    build_analysis_dataset,
    build_inventory_dataset,
    build_order_price_check_dataset,
    compare_plan_with_order,
    compute_dual_strategy_summary,
    compute_inventory_profit,
    compute_missing_market_prices,
    compute_missing_order_market_prices,
    compute_order_profit,
    compute_profit_recommendation_summary,
    compute_tier_diff,
    compute_tier_plan,
    get_previous_tier,
    parse_orders,
    parse_strategy,
    parse_inventory,
    parse_prices,
    recommend_profit_plan,
)
from tobacco_core.price_store import load_price_db, merge_order_products, merge_uploaded_prices, save_price_db, search_prices, upsert_manual_market_prices


st.set_page_config(page_title="梦回唐朝图文店", layout="centered")

st.markdown(
    """
    <style>
    .block-container {
        max-width: fit-content;
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    h1 {
        font-size: 1.65rem;
        line-height: 1.2;
        margin-bottom: 0.5rem;
    }
    .stDataFrame, .stButton, .stFileUploader, .stTextInput, .stAlert {
        margin-left: auto;
        margin-right: auto;
    }
    div[data-testid="stHorizontalBlock"] {
        justify-content: center;
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


def format_price_library(data: pd.DataFrame) -> pd.io.formats.style.Styler:
    ordered = data.copy()
    columns = [col for col in ["商品名称", "当期找货价格", "批发价", "建议零售价"] if col in ordered.columns]
    ordered = ordered[columns]
    styler = ordered.style
    if "当期找货价格" in ordered.columns:
        styler = styler.format({"当期找货价格": "{:,.2f}", "批发价": "{:,.2f}", "建议零售价": "{:,.2f}"}, na_rep="")
        styler = styler.set_properties(subset=["当期找货价格"], **{"font-weight": "700"})
    styler = styler.set_properties(**{"font-size": "0.9rem", "padding": "0.25rem 0.4rem"})
    return styler


def signed_diff_html(value: float, is_money: bool = False) -> str:
    negative = value < 0
    color = "#c62828" if negative else "#2e7d32"
    weight = "700"
    display = money(value) if is_money else integer(value)
    return f"<div style='text-align:center;color:{color};font-weight:{weight};font-size:1.15rem'>{display}</div>"


st.title("梦回唐朝图文店")

if "analysis_started" not in st.session_state:
    st.session_state.analysis_started = False

if "last_saved_price_upload_key" not in st.session_state:
    st.session_state.last_saved_price_upload_key = None

db_prices = load_price_db()

st.subheader("曲靖本地近期行情价格查询")
if "price_search_text" not in st.session_state:
    st.session_state.price_search_text = ""

with st.form("price_search_form", clear_on_submit=False):
    search_col, button_col = st.columns([4, 1], gap="small")
    with search_col:
        search_text = st.text_input(
            "价格查询",
            value=st.session_state.price_search_text,
            placeholder="输入商品名、拼音首字母、条码或盒码",
            label_visibility="collapsed",
        )
    with button_col:
        submitted = st.form_submit_button("查询", use_container_width=True)

if submitted:
    st.session_state.price_search_text = search_text.strip()

price_results = search_prices(db_prices, st.session_state.price_search_text)
st.dataframe(format_price_library(price_results), use_container_width=True, hide_index=True)

st.divider()
st.subheader("1. 上传分析文件")
col1, col2, col3, col4 = st.columns(4)
with col1:
    strategy_file = st.file_uploader("订货量 / 投放表", type=["xlsx"], key="strategy_file")
with col2:
    order_file = st.file_uploader("订单明细（可选）", type=["xlsx"], key="order_file")
with col3:
    inventory_file = st.file_uploader("库存表", type=["xlsx"], key="inventory_file")
with col4:
    price_file = st.file_uploader("上传最新行情价格", type=["xlsx"], key="price_file")

analysis_password = st.text_input("分析密码", type="password", placeholder="请输入开始计算密码")
password_correct = analysis_password == "523626"
current_price_upload_key = None if price_file is None else f"{price_file.name}:{price_file.size}"

if st.button("开始计算", type="primary", use_container_width=True, disabled=not password_correct):
    st.session_state.analysis_started = True

if analysis_password and not password_correct:
    st.warning("密码不正确，无法开始计算。")

if not strategy_file:
    st.session_state.analysis_started = False
    st.info("请先上传订货量/投放表。订单明细和库存表都可以不传。")
    st.stop()

if not password_correct:
    st.session_state.analysis_started = False
    st.info("请输入正确密码后，再点击“开始计算”。")
    st.stop()

if not st.session_state.analysis_started:
    st.info("文件上传完成后，点击“开始计算”再执行分析。")
    st.stop()

if price_file is not None and current_price_upload_key != st.session_state.last_saved_price_upload_key:
    uploaded_prices = parse_prices(price_file)
    db_prices = merge_uploaded_prices(db_prices, uploaded_prices)
    save_price_db(db_prices)
    st.session_state.last_saved_price_upload_key = current_price_upload_key
    st.success(f"已更新行情价格库，本次写入 {len(uploaded_prices)} 条价格记录。")

if db_prices.empty:
    st.error("当前行情价格库为空，无法引用历史批发价，请先上传一份行情价格表初始化价格库。")
    st.stop()

try:
    if order_file is None:
        empty_order = pd.DataFrame(columns=["商品名称", "批发价", "订单量"])
        strategy_items, segment_limits, tier_totals = parse_strategy(strategy_file)
        parsed = ParsedWorkbook(
            orders=empty_order,
            prices=db_prices.copy(),
            strategy_items=strategy_items,
            segment_limits=segment_limits,
            tier_totals=tier_totals,
        )
    else:
        orders = parse_orders(order_file)
        db_prices = merge_order_products(db_prices, orders)
        save_price_db(db_prices)
        strategy_items, segment_limits, tier_totals = parse_strategy(strategy_file)
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

inventory_profit = pd.DataFrame()
missing_market_prices = pd.DataFrame()
missing_order_market_prices = pd.DataFrame()
if inventory_file is not None:
    try:
        inventory_data = build_inventory_dataset(parse_inventory(inventory_file), db_prices)
        inventory_profit = compute_inventory_profit(inventory_data)
        missing_market_prices = compute_missing_market_prices(inventory_data)
    except Exception as exc:
        st.error(f"库存表解析失败：{exc}")

has_order = order_file is not None
order_profit = compute_order_profit(analysis_data) if has_order else pd.DataFrame()
if has_order:
    order_price_check = build_order_price_check_dataset(parsed.orders, db_prices)
    missing_order_market_prices = compute_missing_order_market_prices(order_price_check)
order_total_qty = int(order_profit["订单量"].sum()) if not order_profit.empty else 0
order_total_cost = float(order_profit["订单成本"].sum()) if not order_profit.empty else 0.0
order_total_profit = float(order_profit["订单盈亏"].sum()) if not order_profit.empty else 0.0
current_tier = "三十档"
tier_reason = "按你的使用口径固定为三十档订单" if has_order else "未上传订单，按默认三十档展示可计算结果"
compare_tier = get_previous_tier(current_tier)
current_cost_plan = compute_tier_plan(analysis_data, parsed.segment_limits, current_tier, "cost")
current_profit_plan = compute_tier_plan(analysis_data, parsed.segment_limits, current_tier, "profit")
compare_cost_plan = compute_tier_plan(analysis_data, parsed.segment_limits, compare_tier, "cost") if compare_tier else None
dual_summary = compute_dual_strategy_summary(analysis_data, parsed.segment_limits, parsed.tier_totals)
profit_recommendation_summary = compute_profit_recommendation_summary(analysis_data, parsed.segment_limits)

st.subheader("识别结果")
meta = st.columns(5)
meta[0].metric("订单总条数", integer(order_total_qty))
meta[1].metric("推断当前档位", current_tier)
meta[2].metric("对比档位", compare_tier or "无")
meta[3].metric("订单总成本", money(order_total_cost))
meta[4].metric("订单总盈亏", money(order_total_profit))
st.caption(f"档位推断口径：{tier_reason}。二次自选整段已完全忽略，不参与任何订购、满订和推荐。若本次未上传行情表，则直接使用本地价格库中的批发价/找货价；找货价缺失时回退批发价。")

st.divider()
st.subheader("2. 订单与下一档位最高最贵满订差异")
if not has_order:
    st.info("未上传订单，已跳过订单差异对比。")
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
        st.markdown("<div style='text-align:center;'>与当前订单金额差</div>", unsafe_allow_html=True)
        st.markdown(signed_diff_html(amount_diff, is_money=True), unsafe_allow_html=True)
    cols2 = st.columns(4)
    cols2[0].metric(f"{compare_tier}最高最贵满订条数", integer(compare_cost_plan.total_qty))
    with cols2[1]:
        st.markdown("<div style='text-align:center;'>与当前订单条数差</div>", unsafe_allow_html=True)
        st.markdown(signed_diff_html(qty_diff, is_money=False), unsafe_allow_html=True)
    cols2[2].metric(f"{compare_tier}最高最贵满订盈亏", money(compare_cost_plan.total_profit))
    cols2[3].metric("未满足段上限", integer(compare_cost_plan.unmet_segment_limit))

st.divider()
st.subheader("3. 订单盈亏分析")
if not has_order:
    st.info("未上传订单，已跳过订单盈亏分析。")
else:
    cards = st.columns(4)
    cards[0].metric("订单商品数", integer(len(order_profit)))
    cards[1].metric("订单总成本", money(order_total_cost))
    cards[2].metric("订单总估值", money(float(order_profit["订单估值"].sum()) if not order_profit.empty else 0))
    cards[3].metric("订单总盈亏", money(order_total_profit))
    st.dataframe(
        order_profit[["价位段", "商品名称", "订单量", "批发价", "当期找货价格", "单条毛利", "订单成本", "订单盈亏"]],
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
sum_cols = st.columns(4)
sum_cols[0].metric(f"{current_tier}最贵满订金额", money(current_cost_plan.total_cost))
sum_cols[1].metric(f"{current_tier}利润优先满订金额", money(current_profit_plan.total_cost))
sum_cols[2].metric(f"{current_tier}最贵满订条数", integer(current_cost_plan.total_qty))
sum_cols[3].metric(f"{current_tier}利润优先满订盈亏", money(current_profit_plan.total_profit))
st.dataframe(dual_summary, use_container_width=True, hide_index=True)

selected_detail_tier = st.selectbox("查看满订明细档位", TIER_COLUMNS, index=TIER_COLUMNS.index("三十档"), key="selected_detail_tier")
selected_cost_plan = compute_tier_plan(analysis_data, parsed.segment_limits, selected_detail_tier, "cost")
selected_profit_plan = compute_tier_plan(analysis_data, parsed.segment_limits, selected_detail_tier, "profit")

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
selector_cols = st.columns(2)
default_high = current_tier
default_low = compare_tier or current_tier
selected_high = selector_cols[0].selectbox("高档位", TIER_COLUMNS, index=TIER_COLUMNS.index(default_high))
selected_low = selector_cols[1].selectbox("低档位", TIER_COLUMNS, index=TIER_COLUMNS.index(default_low))
if TIER_COLUMNS.index(selected_high) >= TIER_COLUMNS.index(selected_low):
    st.warning("高档位必须比低档位更高。")
else:
    tier_diff = compute_tier_diff(analysis_data, selected_high, selected_low)
    diff_cols = st.columns(4)
    diff_cols[0].metric("新增品种数", integer(len(tier_diff)))
    diff_cols[1].metric("新增总条数", integer(int(tier_diff["新增量"].sum()) if not tier_diff.empty else 0))
    diff_cols[2].metric("新增总成本", money(float(tier_diff["新增成本"].sum()) if not tier_diff.empty else 0))
    diff_cols[3].metric("新增总盈亏", money(float(tier_diff["新增盈亏"].sum()) if not tier_diff.empty else 0))
    st.dataframe(
        tier_diff[["价位段", "商品名称", "低档位可订量", "高档位可订量", "新增量", "批发价", "新增成本", "新增盈亏"]],
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("6. 各档位最高利润订购推荐")
recommend_tier = st.selectbox("选择推荐档位", TIER_COLUMNS, index=TIER_COLUMNS.index("三十档"), key="recommend_tier")
recommend_compare_tier = get_previous_tier(recommend_tier)
if recommend_compare_tier is None:
    st.info(f"{recommend_tier} 已经没有更低一档可作为对比，暂时无法生成推荐。")
else:
    st.caption(f"先按 {recommend_tier} 利润优先满订生成方案，再从单条毛利最低的商品开始逐条删减；每删一条都校验一次，直到再删就会导致总条数或总金额不再高于 {recommend_compare_tier} 最高最贵满订。")
    profit_recommendation = recommend_profit_plan(analysis_data, parsed.segment_limits, recommend_tier)
    compare_cost_recommendation = compute_tier_plan(analysis_data, parsed.segment_limits, recommend_compare_tier, "cost")
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
st.markdown("**各档位最高利润推荐汇总**")
st.dataframe(
    profit_recommendation_summary[
        [
            "档位",
            "对比下一档",
            "推荐条数",
            "推荐金额",
            "推荐盈亏",
            "利润优先满订条数",
            "利润优先满订盈亏",
            "较利润优先满订条数差",
            "较利润优先满订盈亏差",
            "较下一档最贵满订多条数",
            "较下一档最贵满订多金额",
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

st.divider()
st.subheader("7. 库存估值与盈亏")
if inventory_file is None:
    st.info("上传库存表后，这里会按库存量而不是订单量做估值与盈亏。")
else:
    inv_cols = st.columns(4)
    inv_cols[0].metric("库存条数", integer(int(inventory_profit["库存量"].sum()) if not inventory_profit.empty else 0))
    inv_cols[1].metric("库存成本", money(float(inventory_profit["库存成本"].sum()) if not inventory_profit.empty else 0))
    inv_cols[2].metric("库存市值", money(float(inventory_profit["库存市值"].sum()) if not inventory_profit.empty else 0))
    inv_cols[3].metric("库存盈亏", money(float(inventory_profit["库存盈亏"].sum()) if not inventory_profit.empty else 0))
    st.dataframe(
        inventory_profit[["商品名称", "库存量", "批发价", "当期找货价格", "库存成本", "库存市值", "库存盈亏"]],
        use_container_width=True,
        hide_index=True,
    )

    if not missing_market_prices.empty:
        st.markdown("**以下库存商品缺少行情价格，请补录后保存到行情价格库**")
        editable = missing_market_prices.copy()
        editable = editable[editable["商品名称"].astype(str).str.strip().ne("合计")].copy()
        editable["当期找货价格"] = editable["当期找货价格"].astype("float64")
        if editable.empty:
            st.info("缺少行情价格的库存商品里只有“合计”行，已自动排除。")
        else:
            with st.form("missing_market_prices_form"):
                edited = st.data_editor(
                    editable,
                    use_container_width=True,
                    hide_index=True,
                    key="missing_market_prices_editor",
                )
                save_manual_prices = st.form_submit_button("保存补录行情价格", type="primary")
            if save_manual_prices:
                manual = edited.copy()
                manual = manual[manual["商品名称"].astype(str).str.strip().ne("合计")].copy()
                manual = manual[manual["当期找货价格"].notna()].copy()
                if manual.empty:
                    st.warning("还没有填写可保存的行情价格。")
                else:
                    manual["批发价"] = pd.to_numeric(manual.get("批发价"), errors="coerce")
                    manual["建议零售价"] = pd.to_numeric(manual.get("建议零售价"), errors="coerce")
                    updated_db = upsert_manual_market_prices(db_prices, manual)
                    save_price_db(updated_db)
                    st.success(f"已把 {len(manual)} 条补录行情写入价格库。刷新后会按新价格重新计算库存估值。")
