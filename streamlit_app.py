from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from pypinyin import Style, lazy_pinyin

from tobacco_core.io_utils import read_excel_like
from tobacco_core.logic import (
    Config,
    aggregate_order_history,
    apply_price_overrides,
    build_fill_plan_products,
    build_optimization_plan_products,
    compare_plan_products,
    compare_multiple_configs,
    compute_cumulative_profit_tables,
    compute_fill_scenarios,
    compute_inventory_profit_table,
    compute_optimization,
    compute_profit_analysis,
    merge_price_catalog,
    parse_inventory_table,
    parse_market_price_table,
    parse_order_history_table,
    parse_order_table,
    parse_price_table,
)
from tobacco_core.period_rules import TIER_COLUMN_MAP, apply_period_rules, build_tier_difference, load_period_rules
from tobacco_core.presets import BAND_DEFINITIONS, DEFAULT_PRESETS
from tobacco_core.rating import (
    DEFAULT_CUSTOMER_NAME,
    RatingBenchmarks,
    build_tier_quota_table,
    compute_rating_metrics,
    compute_rating_scores,
    find_customer_result,
    load_rating_results,
)
from tobacco_core.storage import (
    append_history_orders,
    append_market_price_history,
    load_history_orders,
    load_market_price_history,
    load_price_catalog,
    save_price_catalog,
)


st.set_page_config(page_title="卷烟订货测算工具", layout="wide")


PRICE_COLUMNS = ["商品", "指导零售价", "批发价"]
ORDER_COLUMNS = ["商品", "指导零售价", "批发价", "订单量", "金额"]
APP_ROOT = Path(__file__).resolve().parent
DEFAULT_HISTORY_PATH = APP_ROOT / "data" / "previous_quarter_orders_dedup.csv"
DEFAULT_BASE_MARKET_PRICE_PATH = APP_ROOT / "data" / "base_market_prices.xlsx"
DESKTOP_SHORTCUT_NAME = "卷烟订货测算工具.lnk"
ORDER_TIER_OPTIONS = [
    ("tier30", "三十档"),
    ("tier29", "二十九档"),
    ("tier28", "二十八档"),
    ("tier27", "二十七档"),
    ("tier26", "二十六档"),
    ("tier25", "二十五档"),
    ("tier24", "二十四档"),
    ("tier23", "二十三档"),
    ("tier22", "二十二档"),
    ("tier21", "二十一档"),
    ("tier20", "二十档"),
]


def init_state() -> None:
    st.session_state.setdefault("products_df", None)
    st.session_state.setdefault("catalog_df", load_price_catalog())
    st.session_state.setdefault("analysis_result", None)
    st.session_state.setdefault("history_result", None)


def tier_label(tier_id: str) -> str:
    return next((label for value, label in ORDER_TIER_OPTIONS if value == tier_id), tier_id)


def next_lower_tier_id(tier_id: str) -> str | None:
    ordered_ids = [value for value, _ in ORDER_TIER_OPTIONS]
    if tier_id not in ordered_ids:
        return None
    idx = ordered_ids.index(tier_id)
    return ordered_ids[idx + 1] if idx + 1 < len(ordered_ids) else None


def inject_layout_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top right, rgba(198, 219, 255, 0.35), transparent 28%),
                radial-gradient(circle at top left, rgba(255, 232, 201, 0.35), transparent 24%),
                linear-gradient(180deg, #f7f3eb 0%, #fbfaf7 100%);
        }
        .stApp .block-container {
            max-width: 1180px;
            margin-left: auto;
            margin-right: auto;
            padding-top: 1.4rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }
        h1, h2, h3 {
            letter-spacing: 0.01em;
        }
        h1 {
            color: #1f3552;
            font-weight: 800;
        }
        h3 {
            color: #243b53;
            margin-top: 1.2rem;
            padding-bottom: 0.25rem;
            border-bottom: 1px solid rgba(36, 59, 83, 0.08);
        }
        [data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.78);
            border: 1px solid rgba(36, 59, 83, 0.08);
            border-radius: 16px;
            padding: 0.9rem 1rem;
            box-shadow: 0 10px 28px rgba(36, 59, 83, 0.06);
        }
        [data-testid="stFileUploader"],
        [data-testid="stDateInput"],
        [data-testid="stTextInput"],
        [data-testid="stSelectbox"],
        [data-testid="stMultiSelect"] {
            background: rgba(255, 255, 255, 0.72);
            border-radius: 14px;
            padding: 0.25rem 0.4rem 0.4rem 0.4rem;
            border: 1px solid rgba(36, 59, 83, 0.07);
        }
        .stButton > button, .stDownloadButton > button {
            border-radius: 999px;
            border: 1px solid rgba(36, 59, 83, 0.1);
            box-shadow: 0 8px 18px rgba(36, 59, 83, 0.06);
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(250, 247, 240, 0.95), rgba(246, 242, 233, 0.92));
        }
        [data-testid="stDataFrame"],
        [data-testid="stDataEditor"] {
            max-width: 980px;
        }
        [data-testid="stDataFrame"] > div,
        [data-testid="stDataEditor"] > div {
            max-width: 980px;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 12px 26px rgba(36, 59, 83, 0.06);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def read_excel_path(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_excel(path, header=None)


def persist_market_prices(
    market_price_df: pd.DataFrame,
    effective_date: date,
    source_name: str,
    price_df: pd.DataFrame | None = None,
) -> tuple[int, int]:
    if market_price_df is None or market_price_df.empty:
        return 0, len(load_price_catalog())

    catalog_for_save = load_price_catalog()
    if price_df is not None and not price_df.empty:
        catalog_for_save = merge_price_catalog(catalog_for_save, price_df, empty_order_df())

    payload = market_price_df.copy()
    payload["生效日期"] = effective_date
    payload["来源文件"] = source_name
    market_history_df = append_market_price_history(payload)
    latest_market = (
        market_history_df.sort_values(["生效日期", "商品"], kind="stable")
        .drop_duplicates(subset=["商品"], keep="last")[["商品", "行情价"]]
    )

    if catalog_for_save.empty:
        catalog_for_save = pd.DataFrame(columns=["商品", "指导零售价", "批发价", "行情价"])

    missing_names = sorted(set(latest_market["商品"]) - set(catalog_for_save["商品"].astype(str)))
    if missing_names:
        additions = latest_market[latest_market["商品"].isin(missing_names)].copy()
        additions["指导零售价"] = pd.NA
        additions["批发价"] = pd.NA
        additions = additions[["商品", "指导零售价", "批发价", "行情价"]]
        catalog_for_save = pd.concat([catalog_for_save, additions], ignore_index=True)

    catalog_for_save = catalog_for_save.merge(latest_market, on="商品", how="left", suffixes=("", "_latest"))
    catalog_for_save["行情价"] = catalog_for_save["行情价_latest"].combine_first(catalog_for_save["行情价"])
    catalog_for_save = catalog_for_save.drop(columns=["行情价_latest"])
    save_price_catalog(catalog_for_save)
    return len(payload), len(load_price_catalog())


def import_base_market_prices(path: Path, effective_date: date) -> tuple[int, int]:
    raw_df = read_excel_path(path)
    if raw_df.empty:
        return 0, len(load_price_catalog())

    price_df = parse_price_table(raw_df)
    market_price_df = parse_market_price_table(raw_df)
    return persist_market_prices(
        market_price_df=market_price_df,
        effective_date=effective_date,
        source_name=path.name,
        price_df=price_df,
    )


def create_desktop_shortcut() -> Path:
    shortcut_path = Path.home() / "Desktop" / DESKTOP_SHORTCUT_NAME
    run_script_path = APP_ROOT / "run_app.ps1"
    command = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
$Shortcut.TargetPath = 'powershell.exe'
$Shortcut.Arguments = '-ExecutionPolicy Bypass -File "{run_script_path}"'
$Shortcut.WorkingDirectory = '{APP_ROOT}'
$Shortcut.IconLocation = "$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\powershell.exe,0"
$Shortcut.Save()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        check=True,
        cwd=APP_ROOT,
    )
    return shortcut_path


def render_inventory_section(inventory_file, catalog_df: pd.DataFrame, title: str = "库存估值与盈亏") -> None:
    st.subheader(title)
    st.caption("上传库存表后，系统会按当前价格库里的行情价和批发价，计算库存总额、总盈亏和明细表。")
    if inventory_file is None:
        st.info("导入库存表后，这里会显示库存总额、总盈亏和可导出的明细表。")
        return

    inventory_df = parse_inventory_table(read_excel_like(inventory_file))
    if inventory_df.empty:
        st.warning("库存表里没有识别到可用的商品和库存量。")
        return

    inventory_summary, inventory_table = compute_inventory_profit_table(inventory_df, catalog_df)
    summary_metrics(inventory_summary)
    missing_inventory_prices = inventory_table[inventory_table["行情价"].fillna(0).eq(0)]["商品"].tolist()
    if missing_inventory_prices:
        st.warning("这些库存商品还没有行情价，当前按 0 计算市值，请先补行情价：" + "、".join(missing_inventory_prices))
    st.dataframe(inventory_table, use_container_width=True, hide_index=True)
    st.download_button(
        "导出库存盈亏明细表",
        data=dataframe_to_csv_bytes(inventory_table),
        file_name="库存盈亏明细表.csv",
        mime="text/csv",
        use_container_width=True,
    )


def build_actual_order_products(final_df: pd.DataFrame) -> pd.DataFrame:
    order_df = final_df[final_df["订单量"].fillna(0) > 0].copy()
    if order_df.empty:
        return pd.DataFrame(columns=["商品", "分段", "订单量", "批发价", "行情价", "金额"])
    order_df["金额"] = pd.to_numeric(order_df["金额"], errors="coerce").fillna(
        order_df["订单量"].fillna(0) * order_df["批发价"].fillna(0)
    )
    return order_df[["商品", "分段", "订单量", "批发价", "行情价", "金额"]].copy()


def compare_order_plan(
    actual_df: pd.DataFrame,
    plan_df: pd.DataFrame,
    plan_label: str,
    reverse_diff: bool = False,
) -> tuple[dict, pd.DataFrame]:
    actual = actual_df.copy() if actual_df is not None else pd.DataFrame()
    plan = plan_df.copy() if plan_df is not None else pd.DataFrame()

    if actual.empty:
        actual = pd.DataFrame(columns=["商品", "订单量", "金额"])
    if plan.empty:
        plan = pd.DataFrame(columns=["商品", "订单量", "金额"])

    actual["订单量"] = pd.to_numeric(actual.get("订单量"), errors="coerce").fillna(0.0)
    actual["金额"] = pd.to_numeric(actual.get("金额"), errors="coerce").fillna(0.0)
    plan["订单量"] = pd.to_numeric(plan.get("订单量"), errors="coerce").fillna(0.0)
    plan["金额"] = pd.to_numeric(plan.get("金额"), errors="coerce").fillna(0.0)

    actual_base = actual.groupby("商品", as_index=False).agg(提交订单条数=("订单量", "sum"), 提交订单金额=("金额", "sum"))
    plan_base = plan.groupby("商品", as_index=False).agg(**{f"{plan_label}条数": ("订单量", "sum"), f"{plan_label}金额": ("金额", "sum")})
    diff_df = actual_base.merge(plan_base, on="商品", how="outer").fillna(0.0)
    if reverse_diff:
        diff_df["条数差异"] = diff_df["提交订单条数"] - diff_df[f"{plan_label}条数"]
        diff_df["金额差异"] = diff_df["提交订单金额"] - diff_df[f"{plan_label}金额"]
    else:
        diff_df["条数差异"] = diff_df[f"{plan_label}条数"] - diff_df["提交订单条数"]
        diff_df["金额差异"] = diff_df[f"{plan_label}金额"] - diff_df["提交订单金额"]
    diff_df = diff_df[(diff_df["条数差异"] != 0) | (diff_df["金额差异"] != 0)].copy()
    diff_df = diff_df.sort_values(["金额差异", "条数差异", "商品"], ascending=[False, False, True], kind="stable")

    plan_qty = float(plan["订单量"].sum())
    actual_qty = float(actual["订单量"].sum())
    plan_amount = float(plan["金额"].sum())
    actual_amount = float(actual["金额"].sum())
    summary = {
        "提交订单条数": actual_qty,
        "提交订单金额": actual_amount,
        f"{plan_label}条数": plan_qty,
        f"{plan_label}金额": plan_amount,
        "条数差异": actual_qty - plan_qty if reverse_diff else plan_qty - actual_qty,
        "金额差异": actual_amount - plan_amount if reverse_diff else plan_amount - actual_amount,
    }
    return summary, diff_df.reset_index(drop=True)


def build_history_dataset(files) -> pd.DataFrame | None:
    saved_df = load_history_orders()
    if (saved_df is None or saved_df.empty) and DEFAULT_HISTORY_PATH.exists():
        migrated_df = pd.read_csv(DEFAULT_HISTORY_PATH, encoding="utf-8-sig")
        if "订单日期" in migrated_df.columns:
            migrated_df["订单日期"] = pd.to_datetime(migrated_df["订单日期"], errors="coerce").dt.date
        saved_df = append_history_orders(migrated_df)

    frames: list[pd.DataFrame] = []
    for file in files or []:
        raw_df = read_excel_like(file)
        frames.append(parse_order_history_table(raw_df, source_name=file.name))

    if frames:
        imported_df = pd.concat(frames, ignore_index=True)
        saved_df = append_history_orders(imported_df)

    if saved_df is not None and not saved_df.empty:
        return saved_df

    if DEFAULT_HISTORY_PATH.exists():
        df = pd.read_csv(DEFAULT_HISTORY_PATH, encoding="utf-8-sig")
        if "订单日期" in df.columns:
            df["订单日期"] = pd.to_datetime(df["订单日期"], errors="coerce").dt.date
        return df
    return None


def preset_by_id(preset_id: str) -> dict:
    return next((item for item in DEFAULT_PRESETS if item["id"] == preset_id), DEFAULT_PRESETS[0])


def summary_metrics(summary: dict) -> None:
    cols = st.columns(len(summary))
    for col, (label, value) in zip(cols, summary.items(), strict=False):
        if isinstance(value, float):
            if any(word in label for word in ["金额", "毛利", "成本"]):
                col.metric(label, f"{value:,.2f}")
            else:
                col.metric(label, f"{value:,.0f}")
        else:
            col.metric(label, str(value))


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def auto_sync_catalog(
    catalog_df: pd.DataFrame, price_df: pd.DataFrame, order_df: pd.DataFrame
) -> tuple[pd.DataFrame, list[str]]:
    known_names = set(catalog_df["商品"].astype(str)) if not catalog_df.empty else set()
    imported_names = set()
    for frame in [price_df, order_df]:
        if frame is not None and not frame.empty and "商品" in frame.columns:
            imported_names.update(frame["商品"].dropna().astype(str).str.strip().tolist())

    new_names = sorted(name for name in imported_names if name and name not in known_names)
    if not new_names:
        return catalog_df, []

    merged_imports = merge_price_catalog(catalog_df, price_df, order_df)
    additions = merged_imports[merged_imports["商品"].isin(new_names)][["商品", "指导零售价", "批发价", "行情价"]].copy()
    updated_catalog = pd.concat([catalog_df, additions], ignore_index=True)
    save_price_catalog(updated_catalog)
    return load_price_catalog(), new_names


def empty_price_df() -> pd.DataFrame:
    return pd.DataFrame(columns=PRICE_COLUMNS)


def empty_order_df() -> pd.DataFrame:
    return pd.DataFrame(columns=ORDER_COLUMNS)


def make_history_option_labels(history_df: pd.DataFrame) -> dict[str, str]:
    labels: dict[str, str] = {}
    if history_df is None or history_df.empty:
        return labels

    order_keys = history_df[["订单日期", "订单编号", "来源文件"]].drop_duplicates().copy()
    order_keys = order_keys.sort_values(["订单日期", "订单编号", "来源文件"], kind="stable")
    for _, row in order_keys.iterrows():
        order_date = row["订单日期"]
        order_id = row["订单编号"] or "未命名订单"
        source_name = row["来源文件"] or ""
        date_text = order_date.isoformat() if pd.notna(order_date) and order_date else "无日期"
        key = f"{date_text}|{order_id}|{source_name}"
        labels[key] = f"{date_text} | {order_id} | {source_name}"
    return labels


def filter_history_by_keys(history_df: pd.DataFrame, selected_keys: list[str]) -> pd.DataFrame:
    if history_df is None or history_df.empty or not selected_keys:
        return pd.DataFrame(columns=history_df.columns if history_df is not None else [])

    selected_frames: list[pd.DataFrame] = []
    for key in selected_keys:
        date_text, order_id, source_name = key.split("|", 2)
        mask = (
            history_df["订单编号"].fillna("").eq(order_id)
            & history_df["来源文件"].fillna("").eq(source_name)
        )
        if date_text != "无日期":
            mask &= history_df["订单日期"].astype(str).eq(date_text)
        else:
            mask &= history_df["订单日期"].isna()
        selected_frames.append(history_df.loc[mask])
    if not selected_frames:
        return pd.DataFrame(columns=history_df.columns)
    return pd.concat(selected_frames, ignore_index=True)


def build_search_tokens(text: str) -> tuple[str, str]:
    normalized = str(text or "").strip().lower()
    full_pinyin = "".join(lazy_pinyin(normalized))
    initials = "".join(lazy_pinyin(normalized, style=Style.FIRST_LETTER))
    return full_pinyin, initials


def search_catalog_products(catalog_df: pd.DataFrame, query: str) -> pd.DataFrame:
    if catalog_df is None or catalog_df.empty:
        return pd.DataFrame(columns=["商品", "指导零售价", "批发价", "行情价"])
    text = str(query or "").strip().lower()
    if not text:
        return catalog_df.copy()

    rows = []
    for _, row in catalog_df.iterrows():
        name = str(row["商品"])
        name_lower = name.lower()
        full_pinyin, initials = build_search_tokens(name)
        if text in name_lower or text in full_pinyin or text in initials:
            rows.append(row)
    if not rows:
        return pd.DataFrame(columns=catalog_df.columns)
    return pd.DataFrame(rows).reset_index(drop=True)


def main() -> None:
    init_state()
    inject_layout_styles()

    st.title("卷烟订货测算工具")
    st.caption("价格库长期保存。你每期只要导入本期订货量表、草稿或最终订单，再点按钮计算即可。")

    with st.sidebar:
        st.header("规则配置")
        preset_id = st.selectbox(
            "档位模板",
            options=[item["id"] for item in DEFAULT_PRESETS],
            format_func=lambda item: preset_by_id(item)["name"],
        )
        preset = preset_by_id(preset_id)
        target_total = int(preset["target_total"])
        supply_total = int(preset["supply_total"])
        band_caps: dict[str, int] = dict(preset["band_caps"])
        st.caption("这些数值由公司规则决定，页面内不再手动加减。导入本期订货量表后会自动按当期规则覆盖。")
        st.markdown(f"目标总条数：`{target_total}`")
        st.markdown(f"投放量：`{supply_total}`")
        for band in BAND_DEFINITIONS:
            st.markdown(f"{band['name']} 上限：`{int(band_caps.get(band['name'], 0))}`")
        st.caption("不在上述价位段内的品种会自动归入“按档位投放”。")
        compare_ids = st.multiselect(
            "对比档位",
            options=[item["id"] for item in DEFAULT_PRESETS],
            default=["tier30", "tier29"],
            format_func=lambda item: preset_by_id(item)["name"],
        )

    st.subheader("1. 导入文件")
    left, mid, right, far_right = st.columns(4)
    with left:
        guide_file = st.file_uploader("新品或更新价格表", type=["xlsx", "xls", "csv"])
    with mid:
        price_file = st.file_uploader("补充价格表", type=["xlsx", "xls", "csv"])
    with right:
        draft_order_file = st.file_uploader("草稿订单", type=["xlsx", "xls", "csv"])
    with far_right:
        final_order_file = st.file_uploader("最终订单", type=["xlsx", "xls", "csv"])

    selected_order_tier = st.selectbox(
        "提交订单档位",
        options=[value for value, _ in ORDER_TIER_OPTIONS],
        index=0,
        format_func=tier_label,
    )

    period_rule_file = st.file_uploader("本期订货量表", type=["xlsx", "xls", "csv"])
    market_price_file = st.file_uploader("当期找货价格表", type=["xlsx", "xls", "csv"])
    inventory_file = st.file_uploader("库存表", type=["xlsx", "xls", "csv"])
    history_files = st.file_uploader("历史订单明细表", type=["xlsx", "xls", "csv"], accept_multiple_files=True)
    rating_result_file = st.file_uploader("官方测评结果表", type=["xlsx", "xls", "csv"])
    market_effective_date = st.date_input("当期找货价格生效日期", value=date.today())
    if DEFAULT_BASE_MARKET_PRICE_PATH.exists():
        st.caption(f"系统基础行情表：{DEFAULT_BASE_MARKET_PRICE_PATH}")
    else:
        st.caption("系统基础行情表暂未放入 data 目录。")

    action_col, market_col, base_col, shortcut_col, clear_col = st.columns(5)
    with action_col:
        run_analysis = st.button("开始计算", use_container_width=True, type="primary")
    with market_col:
        save_market_prices = st.button("保存当期行情价", use_container_width=True)
    with base_col:
        import_base_prices = st.button(
            "导入基础行情表",
            use_container_width=True,
            disabled=not DEFAULT_BASE_MARKET_PRICE_PATH.exists(),
        )
    with shortcut_col:
        create_shortcut_button = st.button("创建桌面快捷方式", use_container_width=True)
    with clear_col:
        clear_results = st.button("清空本次结果", use_container_width=True)

    if clear_results:
        st.session_state["analysis_result"] = None
        st.session_state["history_result"] = None
        st.rerun()

    if create_shortcut_button:
        try:
            shortcut_path = create_desktop_shortcut()
            st.success(f"桌面快捷方式已创建：{shortcut_path}")
        except Exception as exc:
            st.error(f"创建桌面快捷方式失败：{exc}")

    if import_base_prices:
        imported_count, catalog_count = import_base_market_prices(DEFAULT_BASE_MARKET_PRICE_PATH, market_effective_date)
        st.session_state["catalog_df"] = load_price_catalog()
        if imported_count == 0:
            st.warning("基础行情表没有识别到可导入的商品和行情价。")
        else:
            st.success(f"已从基础行情表导入 {imported_count} 条行情，并更新系统价格库，共 {catalog_count} 个商品。")

    if save_market_prices:
        if market_price_file is None:
            st.warning("请先导入当期找货价格表，再保存。")
        else:
            market_price_df = parse_market_price_table(read_excel_like(market_price_file))
            if market_price_df.empty:
                st.warning("这份找货价格表里没有识别到可用的商品和行情价。")
            else:
                imported_count, catalog_count = persist_market_prices(
                    market_price_df=market_price_df,
                    effective_date=market_effective_date,
                    source_name=getattr(market_price_file, "name", ""),
                )
                st.session_state["catalog_df"] = load_price_catalog()
                st.success(
                    f"已保存 {imported_count} 条当期行情价，并更新系统价格库到 {catalog_count} 个商品；历史利润测算会自动按日期回退使用。"
                )

    st.subheader("2. 价格查询")
    st.caption("支持按商品名、拼音片段、拼音首字母片段查询。查到后可以直接修改行情价并保存进价格库。")
    search_query = st.text_input("输入商品名、拼音或首字母", value="", placeholder="例如：云烟 / yuny / yy")
    live_catalog_df = st.session_state["catalog_df"]
    search_result_df = search_catalog_products(live_catalog_df, search_query)
    if search_result_df.empty:
        st.info("当前没有匹配到商品。")
    else:
        search_edit_df = st.data_editor(
            search_result_df[["商品", "行情价", "指导零售价", "批发价"]].copy(),
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key="price_search_editor",
            column_config={
                "商品": st.column_config.TextColumn(disabled=True),
                "行情价": st.column_config.NumberColumn(format="%.2f"),
                "指导零售价": st.column_config.NumberColumn(format="%.2f", disabled=True),
                "批发价": st.column_config.NumberColumn(format="%.2f", disabled=True),
            },
        )
        search_save_col, search_export_col = st.columns(2)
        with search_save_col:
            if st.button("保存查询结果里的行情价", use_container_width=True):
                latest_catalog = load_price_catalog()
                edited_market = search_edit_df[["商品", "行情价"]].copy()
                latest_catalog = latest_catalog.merge(edited_market, on="商品", how="left", suffixes=("", "_edit"))
                latest_catalog["行情价"] = latest_catalog["行情价_edit"].combine_first(latest_catalog["行情价"])
                latest_catalog = latest_catalog.drop(columns=["行情价_edit"])
                save_price_catalog(latest_catalog)
                st.session_state["catalog_df"] = load_price_catalog()
                st.success(f"已保存 {len(search_edit_df)} 个匹配商品的行情价。")
                st.rerun()
        with search_export_col:
            st.download_button(
                "导出查询结果",
                data=dataframe_to_csv_bytes(search_result_df[["商品", "行情价", "指导零售价", "批发价"]]),
                file_name="卷烟价格查询结果.csv",
                mime="text/csv",
                use_container_width=True,
            )

    price_source = guide_file or price_file
    active_order_file = final_order_file or draft_order_file
    catalog_df = st.session_state["catalog_df"]
    analysis_result = st.session_state["analysis_result"]

    if run_analysis:
        price_df = parse_price_table(read_excel_like(price_source)) if price_source else empty_price_df()
        order_df = parse_order_table(read_excel_like(active_order_file)) if active_order_file else empty_order_df()
        order_history_df = (
            parse_order_history_table(read_excel_like(active_order_file), source_name=getattr(active_order_file, "name", ""))
            if active_order_file
            else pd.DataFrame()
        )

        catalog_df, new_products = auto_sync_catalog(catalog_df, price_df, order_df)
        st.session_state["catalog_df"] = catalog_df

        merged_df = merge_price_catalog(catalog_df, price_df, order_df)
        if merged_df is None or merged_df.empty:
            st.session_state["analysis_result"] = None
        else:
            analysis_result = {
                "merged_df": merged_df,
                "new_products": new_products,
                "has_period_rule": bool(period_rule_file),
                "has_order": bool(active_order_file),
                "using_final_order": bool(final_order_file),
                "using_draft_order": bool(draft_order_file and not final_order_file),
                "period_rule_file": period_rule_file,
                "order_history_df": order_history_df,
            }
            st.session_state["analysis_result"] = analysis_result
            st.session_state["products_df"] = merged_df

    analysis_result = st.session_state["analysis_result"]
    if analysis_result is None:
        st.info("先把这次要用的文件导入好，再点“开始计算”。只导入本期订货量表，也可以先出理论测算。")
        return

    merged_df = analysis_result["merged_df"]
    if merged_df is None or merged_df.empty:
        st.info("先建立并保存价格库；之后平时只导入你的订单和本期规则就可以用了。")
        return

    st.success(f"当前商品库共 {len(merged_df)} 个商品。所有利润相关结果优先按行情价计算；没有行情价时按批发价计算。")
    if analysis_result.get("has_period_rule") and not analysis_result.get("has_order"):
        st.info("当前未导入订单，系统会先按本期订货量表做理论测算。")
    if analysis_result.get("using_final_order"):
        st.info("当前使用“最终订单”作为正式订单分析依据。重新导入新的最终订单会自动覆盖。")
    elif analysis_result.get("using_draft_order"):
        st.info("当前使用“草稿订单”做临时分析；后续导入最终订单会自动覆盖。")

    new_products = analysis_result.get("new_products", [])
    if new_products:
        st.info("已自动加入价格库的新品：" + "、".join(new_products))

    final_df = apply_price_overrides(merged_df, None)
    period_rules_df = load_period_rules(period_rule_file)
    final_df, period_summary = apply_period_rules(final_df, period_rules_df, preset_id)
    config = Config(target_total=target_total, supply_total=supply_total, band_caps=dict(band_caps))
    if period_summary:
        if "可订货量合计" in period_summary:
            config.target_total = int(period_summary["可订货量合计"])
        if "投放量" in period_summary:
            config.supply_total = int(period_summary["投放量"])
        if period_summary.get("band_caps"):
            config.band_caps.update(period_summary["band_caps"])
        with st.sidebar:
            st.markdown("---")
            st.caption("当前已按本期订货量表覆盖公司规则")
            st.markdown(f"目标总条数：`{config.target_total}`")
            st.markdown(f"投放量：`{config.supply_total}`")
            for band in BAND_DEFINITIONS:
                if band["name"] in config.band_caps:
                    st.markdown(f"{band['name']} 上限：`{int(config.band_caps[band['name']])}`")

    if new_products:
        pending_market = final_df[(final_df["商品"].isin(new_products)) & (final_df["行情价"].isna())]["商品"].tolist()
        if pending_market:
            st.warning("发现新品但还没填写找货行情价：" + "、".join(pending_market))

    st.subheader("3. 最优订货组合")
    st.caption("当前按“行情价 - 批发价”的单条毛利最大化推荐；没有行情价时自动按批发价计算，毛利为 0。")
    opt_summary, opt_table = compute_optimization(final_df, config)
    summary_metrics(opt_summary)
    st.dataframe(opt_table, use_container_width=True, hide_index=True)
    if analysis_result.get("has_order"):
        actual_order_df = build_actual_order_products(final_df)
        optimal_plan_df = build_optimization_plan_products(final_df, config)
        opt_compare_summary, opt_compare_df = compare_order_plan(actual_order_df, optimal_plan_df, "最优订货组合")
        st.markdown("**提交订单与最优订货组合差异**")
        summary_metrics(opt_compare_summary)
        if opt_compare_df.empty:
            st.info("当前提交订单与最优订货组合在条数和金额上没有差异。")
        else:
            st.dataframe(opt_compare_df, use_container_width=True, hide_index=True)

    st.subheader("4. 订单盈亏分析")
    if not analysis_result.get("has_order"):
        st.info("当前没有导入草稿订单或最终订单，这里暂不显示订单盈亏分析。")
    else:
        profit_summary, profit_table = compute_profit_analysis(final_df)
        if profit_table.empty:
            st.warning("已导入订单，但当前没有识别到可参与利润分析的订单商品，请检查订单表头或商品匹配。")
        else:
            summary_metrics(profit_summary)
            st.dataframe(profit_table, use_container_width=True, hide_index=True)
            next_tier_id = next_lower_tier_id(selected_order_tier)
            next_tier_preset = next((item for item in DEFAULT_PRESETS if item["id"] == next_tier_id), None) if next_tier_id else None
            if next_tier_id is None:
                st.info("当前已是最低可选档位，无法继续做下一档位比较。")
            elif next_tier_preset is None:
                st.warning(f"当前规则只支持计算到 {tier_label('tier26')}，暂时无法生成 {tier_label(next_tier_id)} 的最高最贵满订方案。")
            else:
                next_config = Config(
                    target_total=int(next_tier_preset["target_total"]),
                    supply_total=int(next_tier_preset["supply_total"]),
                    band_caps=dict(next_tier_preset["band_caps"]),
                )
                next_tier_df = final_df.copy()
                if period_rules_df is not None and not period_rules_df.empty:
                    next_tier_df, next_summary = apply_period_rules(final_df, period_rules_df, next_tier_id)
                    if "可订货量合计" in next_summary:
                        next_config.target_total = int(next_summary["可订货量合计"])
                    if "投放量" in next_summary:
                        next_config.supply_total = int(next_summary["投放量"])
                    if next_summary.get("band_caps"):
                        next_config.band_caps.update(next_summary["band_caps"])
                next_full_plan_df = build_fill_plan_products(next_tier_df, next_config, highest=True)
                next_compare_summary, next_compare_df = compare_order_plan(
                    build_actual_order_products(final_df),
                    next_full_plan_df,
                    f"{tier_label(next_tier_id)}最高最贵满订",
                    reverse_diff=True,
                )
                st.markdown(f"**提交订单与下一档位最高最贵满订差异（当前提交档位：{tier_label(selected_order_tier)}）**")
                summary_metrics(next_compare_summary)
                if next_compare_df.empty:
                    st.info("当前提交订单与下一档位最高最贵满订在条数和金额上没有差异。")
                else:
                    st.dataframe(next_compare_df, use_container_width=True, hide_index=True)

    st.subheader("5. 本期档位最高满订汇总")
    st.caption("按和页面其它位置一致的“满档最高金额”口径，汇总各档位本期最高满订条数和金额。")
    period_tier_rows = []
    if period_rules_df is not None and not period_rules_df.empty:
        for tier_id, tier_column in TIER_COLUMN_MAP.items():
            if tier_column not in period_rules_df.columns:
                continue
            tier_preset = preset_by_id(tier_id)
            tier_config = Config(
                target_total=int(tier_preset["target_total"]),
                supply_total=int(tier_preset["supply_total"]),
                band_caps=dict(tier_preset["band_caps"]),
            )
            tier_df, tier_summary = apply_period_rules(final_df, period_rules_df, tier_id)
            if "可订货量合计" in tier_summary:
                tier_config.target_total = int(tier_summary["可订货量合计"])
            if "投放量" in tier_summary:
                tier_config.supply_total = int(tier_summary["投放量"])
            if tier_summary.get("band_caps"):
                tier_config.band_caps.update(tier_summary["band_caps"])
            tier_fill_table = build_fill_plan_products(tier_df, tier_config, highest=True)
            if tier_fill_table.empty:
                continue
            period_tier_rows.append(
                {
                    "档位": tier_preset["name"],
                    "最高满订条数": float(pd.to_numeric(tier_fill_table["订单量"], errors="coerce").fillna(0).sum()),
                    "最高满订金额": float(pd.to_numeric(tier_fill_table["金额"], errors="coerce").fillna(0).sum()),
                    "可参与测算条数": float(pd.to_numeric(tier_df["可订量"], errors="coerce").fillna(0).sum()),
                    "投放量": tier_config.supply_total,
                }
            )

    if period_tier_rows:
        tier_order = {preset_by_id(item["id"])["name"]: index for index, item in enumerate(DEFAULT_PRESETS)}
        period_tier_df = pd.DataFrame(period_tier_rows)
        period_tier_df["排序"] = period_tier_df["档位"].map(tier_order).fillna(999)
        period_tier_df = period_tier_df.sort_values("排序", kind="stable").drop(columns=["排序"])
        st.dataframe(period_tier_df, use_container_width=True, hide_index=True)
    else:
        st.info("导入本期订货量表后，这里会自动列出涉及档位的最高满订条数和金额。")

    st.subheader("6. 档位差异烟")
    st.caption("按两个档位“最高最贵满订方案”的商品差异，列出高档位比低档位多出来的烟，以及这些差异烟的成本和利润。")
    diff_col1, diff_col2 = st.columns(2)
    with diff_col1:
        higher_diff_id = st.selectbox(
            "高档位",
            options=[item["id"] for item in DEFAULT_PRESETS],
            index=0,
            format_func=lambda item: preset_by_id(item)["name"],
            key="higher_diff_id",
        )
    with diff_col2:
        lower_diff_id = st.selectbox(
            "低档位",
            options=[item["id"] for item in DEFAULT_PRESETS],
            index=1,
            format_func=lambda item: preset_by_id(item)["name"],
            key="lower_diff_id",
        )
    if higher_diff_id == lower_diff_id:
        st.info("请选择两个不同的档位进行差异比较。")
    else:
        higher_preset = next((item for item in DEFAULT_PRESETS if item["id"] == higher_diff_id), None)
        lower_preset = next((item for item in DEFAULT_PRESETS if item["id"] == lower_diff_id), None)
        if higher_preset is None or lower_preset is None:
            st.warning("当前规则表还没有这两个档位的完整配置，暂时无法比较。")
        else:
            higher_config = Config(
                target_total=int(higher_preset["target_total"]),
                supply_total=int(higher_preset["supply_total"]),
                band_caps=dict(higher_preset["band_caps"]),
            )
            lower_config = Config(
                target_total=int(lower_preset["target_total"]),
                supply_total=int(lower_preset["supply_total"]),
                band_caps=dict(lower_preset["band_caps"]),
            )
            higher_df = final_df.copy()
            lower_df = final_df.copy()
            if period_rules_df is not None and not period_rules_df.empty:
                higher_df, higher_summary = apply_period_rules(final_df, period_rules_df, higher_diff_id)
                lower_df, lower_summary = apply_period_rules(final_df, period_rules_df, lower_diff_id)
                if "可订货量合计" in higher_summary:
                    higher_config.target_total = int(higher_summary["可订货量合计"])
                if "投放量" in higher_summary:
                    higher_config.supply_total = int(higher_summary["投放量"])
                if higher_summary.get("band_caps"):
                    higher_config.band_caps.update(higher_summary["band_caps"])
                if "可订货量合计" in lower_summary:
                    lower_config.target_total = int(lower_summary["可订货量合计"])
                if "投放量" in lower_summary:
                    lower_config.supply_total = int(lower_summary["投放量"])
                if lower_summary.get("band_caps"):
                    lower_config.band_caps.update(lower_summary["band_caps"])
            higher_plan_df = build_fill_plan_products(higher_df, higher_config, highest=True)
            lower_plan_df = build_fill_plan_products(lower_df, lower_config, highest=True)
            diff_summary, diff_table = compare_plan_products(higher_plan_df, lower_plan_df)
            summary_metrics(diff_summary)
            st.dataframe(diff_table, use_container_width=True, hide_index=True)

    render_inventory_section(inventory_file, live_catalog_df, "7. 库存估值与盈亏")

    st.subheader("8. 历史订单汇总")
    st.caption("用于季度评档。历史订单会自动长期保存；新上传时会按订单日期和整单金额去重，重复订单只保留一单。")

    history_query_col, history_clear_col = st.columns(2)
    with history_query_col:
        query_history = st.button("查询汇总", use_container_width=True)
    with history_clear_col:
        clear_history = st.button("清空历史查询结果", use_container_width=True)

    if clear_history:
        st.session_state["history_result"] = None
        st.rerun()

    history_df = build_history_dataset(history_files) if history_files else None
    if history_df is None or history_df.empty:
        st.info("上传多份历史订单明细后，这里会显示按时间段汇总的结果。")
        return

    available_dates = history_df["订单日期"].dropna().sort_values()
    min_date = available_dates.iloc[0] if not available_dates.empty else date.today()
    max_date = available_dates.iloc[-1] if not available_dates.empty else date.today()
    date_col1, date_col2 = st.columns(2)
    with date_col1:
        start_date = st.date_input("开始日期", value=min_date, min_value=min_date, max_value=max_date)
    with date_col2:
        end_date = st.date_input("结束日期", value=max_date, min_value=min_date, max_value=max_date)

    if query_history:
        history_summary, order_history_table, product_history_table = aggregate_order_history(history_df, start_date, end_date)
        st.session_state["history_result"] = {
            "summary": history_summary,
            "order_table": order_history_table,
            "product_table": product_history_table,
            "filtered_df": history_df[
                history_df["订单日期"].between(start_date, end_date, inclusive="both")
                if "订单日期" in history_df.columns
                else []
            ].copy()
            if "订单日期" in history_df.columns
            else history_df.copy(),
        }

    history_result = st.session_state["history_result"]
    if history_result is None:
        st.info("选好时间段后，点“查询汇总”再看结果。")
        return

    summary_metrics(history_result["summary"])
    st.markdown("**按次汇总**")
    st.dataframe(history_result["order_table"], use_container_width=True, hide_index=True)

    st.markdown("**按商品汇总**")
    st.dataframe(history_result["product_table"], use_container_width=True, hide_index=True)

    st.subheader("9. 年度累计")
    st.caption("按每年1月1日至当前日期累计已确认订单，并结合你保存过的行情价快照生成年度利润表。若当期缺少行情价，会自动沿用上期价格。")

    annual_start = date(date.today().year, 1, 1)
    annual_history_df = history_df[(history_df["订单日期"] >= annual_start) & (history_df["订单日期"] <= date.today())].copy()
    current_confirmed_df = pd.DataFrame(columns=annual_history_df.columns)
    if analysis_result.get("using_final_order"):
        current_confirmed_df = analysis_result.get("order_history_df", pd.DataFrame()).copy()
        if not current_confirmed_df.empty and "订单编号" in annual_history_df.columns and "订单编号" in current_confirmed_df.columns:
            current_confirmed_df = current_confirmed_df[~current_confirmed_df["订单编号"].isin(set(annual_history_df["订单编号"].dropna()))]

    annual_orders_df = pd.concat([annual_history_df, current_confirmed_df], ignore_index=True) if not current_confirmed_df.empty else annual_history_df
    annual_orders_df = annual_orders_df.drop_duplicates(subset=["订单编号", "商品", "订单量", "金额"], keep="last")

    market_history_df = load_market_price_history()
    annual_profit_summary, annual_product_profit_table, annual_order_profit_table = compute_cumulative_profit_tables(annual_orders_df, market_history_df)
    annual_summary = {
        "累计起始日期": annual_start.isoformat(),
        "累计总金额": annual_profit_summary["累计总金额"],
        "累计总条数": annual_profit_summary["累计总条数"],
        "累计总利润": annual_profit_summary["累计总利润"],
    }
    summary_metrics(annual_summary)

    annual_product_summary = (
        annual_orders_df.groupby("商品", as_index=False)
        .agg(累计订货量=("订单量", "sum"), 累计订货金额=("金额", "sum"))
        .sort_values(["累计订货量", "累计订货金额"], ascending=[False, False], kind="stable")
    )
    st.markdown("**年度各品种累计订货量**")
    st.dataframe(annual_product_summary, use_container_width=True, hide_index=True)

    st.markdown("**年度各品种累计利润表**")
    st.dataframe(annual_product_profit_table, use_container_width=True, hide_index=True)

    st.markdown("**年度订单总盈亏表**")
    st.dataframe(annual_order_profit_table, use_container_width=True, hide_index=True)

    st.subheader("10. 评档测算")
    st.caption("从已查询出的历史订单里勾选要参与评档的订单，再和本期订单或本期理论打满结果合并测算。")

    filtered_history_df = history_result.get("filtered_df")
    option_map = make_history_option_labels(filtered_history_df)
    selected_history_keys = st.multiselect(
        "选择参与评档的历史订单",
        options=list(option_map.keys()),
        default=list(option_map.keys()),
        format_func=lambda item: option_map[item],
    )

    selected_history_df = filter_history_by_keys(filtered_history_df, selected_history_keys)
    history_selected_qty = float(selected_history_df["订单量"].fillna(0).sum()) if not selected_history_df.empty else 0.0
    history_selected_amount = float(
        selected_history_df["金额"].fillna(selected_history_df["订单量"].fillna(0) * selected_history_df["批发价"].fillna(0)).sum()
    ) if not selected_history_df.empty else 0.0

    actual_order_qty = float(final_df["订单量"].fillna(0).sum())
    actual_order_amount = float(
        final_df["金额"].fillna(final_df["订单量"].fillna(0) * final_df["批发价"].fillna(0)).sum()
    )

    current_max_fill_df = build_fill_plan_products(final_df, config, highest=True)
    current_max_fill_amount = float(pd.to_numeric(current_max_fill_df["金额"], errors="coerce").fillna(0).sum()) if not current_max_fill_df.empty else 0.0
    current_max_fill_qty = float(pd.to_numeric(current_max_fill_df["订单量"], errors="coerce").fillna(0).sum()) if not current_max_fill_df.empty else 0.0

    grade_compare_df = pd.DataFrame(
        [
            {
                "测算口径": "历史累计 + 本期实际订单",
                "历史订单数": len(selected_history_keys),
                "历史累计条数": history_selected_qty,
                "历史累计金额": history_selected_amount,
                "本期条数": actual_order_qty,
                "本期金额": actual_order_amount,
                "合计条数": history_selected_qty + actual_order_qty,
                "合计金额": history_selected_amount + actual_order_amount,
            },
            {
                "测算口径": "历史累计 + 本期理论最高打满",
                "历史订单数": len(selected_history_keys),
                "历史累计条数": history_selected_qty,
                "历史累计金额": history_selected_amount,
                "本期条数": current_max_fill_qty,
                "本期金额": current_max_fill_amount,
                "合计条数": history_selected_qty + current_max_fill_qty,
                "合计金额": history_selected_amount + current_max_fill_amount,
            },
        ]
    )
    st.dataframe(grade_compare_df, use_container_width=True, hide_index=True)

    st.subheader("11. 季度评档参考")
    st.caption("这里按曲靖分档规则做参考测算。精确官方分值仍依赖同期全量客户最高值；这版会先结合你选中的历史订单、本期订单和可编辑参考基准来估算。")

    official_results_df = load_rating_results(rating_result_file)
    customer_result_df = find_customer_result(official_results_df, DEFAULT_CUSTOMER_NAME)
    if not customer_result_df.empty:
        st.markdown("**最近一次官方结果**")
        st.dataframe(customer_result_df, use_container_width=True, hide_index=True)
        valid_results_df = official_results_df[official_results_df["测算档位"].notna() & official_results_df["测算前档位"].notna()].copy()
        quota_df = build_tier_quota_table(len(valid_results_df))
        customer_idx = customer_result_df.index[0]
        overall_rank = valid_results_df.index.get_indexer([customer_idx])[0] + 1 if customer_idx in valid_results_df.index else None
        same_tier_df = valid_results_df[valid_results_df["测算档位"] == customer_result_df.iloc[0]["测算档位"]]
        tier_rank = same_tier_df.index.get_indexer([customer_idx])[0] + 1 if customer_idx in same_tier_df.index else None
        official_summary = {
            "参与测评客户数": int(len(valid_results_df)),
            "三十档理论名额": int(quota_df.loc[quota_df["档位"] == "三十档", "预计客户数"].iloc[0]),
            "二十九档理论名额": int(quota_df.loc[quota_df["档位"] == "二十九档", "预计客户数"].iloc[0]),
            "当前官方档位": customer_result_df.iloc[0]["测算档位"],
            "上期档位": customer_result_df.iloc[0]["测算前档位"],
        }
        summary_metrics(official_summary)
        rank_summary = {
            "官方排序参考": overall_rank or "-",
            "当前档内排序": tier_rank or "-",
            "当前档位人数": int(len(same_tier_df)),
            "忽略未测评新户后总人数": int(len(valid_results_df)),
        }
        summary_metrics(rank_summary)
        st.caption("这一步已经按你的要求忽略了公示表里没有完整测评信息的新办证客户。")

    actual_current_df = final_df[final_df["订单量"].fillna(0) > 0][["商品", "订单量", "金额", "行情价", "批发价"]].copy()
    theory_current_df = build_fill_plan_products(final_df, config, highest=True)[["商品", "订单量", "金额", "行情价", "批发价"]].copy()

    class12_threshold = st.number_input("一二类烟判定零售价下限", min_value=0.0, value=130.0, step=10.0)
    actual_metrics = compute_rating_metrics(selected_history_df, actual_current_df, class12_threshold=class12_threshold)
    theory_metrics = compute_rating_metrics(selected_history_df, theory_current_df, class12_threshold=class12_threshold)

    benchmark_defaults = {
        "quantity_max": max(actual_metrics["购进量"], theory_metrics["购进量"], 1.0),
        "amount_max": max(actual_metrics["购进金额"], theory_metrics["购进金额"], 1.0),
        "avg_price_max": max(actual_metrics["条均价"], theory_metrics["条均价"], 1.0),
        "class12_ratio_max": max(actual_metrics["一二类烟购进量占比"], theory_metrics["一二类烟购进量占比"], 1.0),
        "class12_amount_max": max(actual_metrics["一二类烟购进金额"], theory_metrics["一二类烟购进金额"], 1.0),
    }

    st.markdown("**参考最高值设置**")
    bench_col1, bench_col2, bench_col3 = st.columns(3)
    with bench_col1:
        quantity_max = st.number_input("最高购进量", min_value=0.0, value=float(benchmark_defaults["quantity_max"]), step=1.0)
        amount_max = st.number_input("最高购进金额", min_value=0.0, value=float(benchmark_defaults["amount_max"]), step=100.0)
    with bench_col2:
        avg_price_max = st.number_input("最高条均价", min_value=0.0, value=float(benchmark_defaults["avg_price_max"]), step=1.0)
        class12_ratio_max = st.number_input("最高一二类烟量占比", min_value=0.0, value=float(benchmark_defaults["class12_ratio_max"]), step=0.01)
    with bench_col3:
        class12_amount_max = st.number_input("最高一二类烟金额", min_value=0.0, value=float(benchmark_defaults["class12_amount_max"]), step=100.0)

    benchmarks = RatingBenchmarks(
        quantity_max=quantity_max,
        amount_max=amount_max,
        avg_price_max=avg_price_max,
        class12_ratio_max=class12_ratio_max,
        class12_amount_max=class12_amount_max,
    )

    actual_score_summary, actual_score_table = compute_rating_scores(actual_metrics, benchmarks)
    theory_score_summary, theory_score_table = compute_rating_scores(theory_metrics, benchmarks)

    compare_score_df = pd.DataFrame(
        [
            {
                "测算口径": "历史累计 + 本期实际订单",
                "参考综合得分": actual_score_summary["参考综合得分"],
                "购进量": actual_score_summary["购进量"],
                "购进金额": actual_score_summary["购进金额"],
                "条均价": actual_score_summary["条均价"],
                "一二类烟量占比": actual_score_summary["一二类烟量占比"],
                "一二类烟金额": actual_score_summary["一二类烟金额"],
            },
            {
                "测算口径": "历史累计 + 本期理论最高打满",
                "参考综合得分": theory_score_summary["参考综合得分"],
                "购进量": theory_score_summary["购进量"],
                "购进金额": theory_score_summary["购进金额"],
                "条均价": theory_score_summary["条均价"],
                "一二类烟量占比": theory_score_summary["一二类烟量占比"],
                "一二类烟金额": theory_score_summary["一二类烟金额"],
            },
        ]
    )
    st.dataframe(compare_score_df, use_container_width=True, hide_index=True)
    st.info("精确官方分数、第一名订购数量，无法仅凭公示档位表单独倒推；当前页面给的是结合你真实季度订单后做的参考测算。若后面有客户经理发来的详细测评分值单，我可以继续把它校准得更准。")

    score_tab1, score_tab2 = st.tabs(["本期实际订单得分拆解", "本期理论最高打满得分拆解"])
    with score_tab1:
        st.dataframe(actual_score_table, use_container_width=True, hide_index=True)
    with score_tab2:
        st.dataframe(theory_score_table, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
