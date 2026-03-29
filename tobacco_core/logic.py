from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from .io_utils import find_column, normalize_dataframe, to_number
from .period_rules import apply_period_rules
from .presets import BAND_DEFINITIONS


@dataclass
class Config:
    target_total: int
    supply_total: int
    band_caps: dict[str, int]


BAND_DISPLAY_ORDER = {
    "14-15段": 0,
    "13段": 1,
    "12段": 2,
    "11段": 3,
    "10段": 4,
    "8-9段": 5,
    "按档位投放": 6,
}


def parse_price_table(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_dataframe(raw_df, ["商品"])
    if df.empty:
        return pd.DataFrame(columns=["商品", "指导零售价", "批发价"])

    name_col = find_column(df.columns, ["商品", "商品名称"])
    wholesale_col = find_column(df.columns, ["批发价", "批发价格"])
    guide_col = find_column(df.columns, ["建议零售价", "零售价"])

    parsed = pd.DataFrame({"商品": df[name_col].astype(str).str.strip() if name_col else ""})
    parsed["指导零售价"] = df[guide_col].map(to_number) if guide_col else None
    parsed["批发价"] = df[wholesale_col].map(to_number) if wholesale_col else None
    return parsed[parsed["商品"].ne("") & parsed["商品"].ne("合计")]


def parse_market_price_table(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_dataframe(raw_df, ["商品"])
    if df.empty:
        return pd.DataFrame(columns=["商品", "行情价"])

    name_col = find_column(df.columns, ["商品", "商品名称"])
    market_col = find_column(df.columns, ["行情价", "找货价", "市场价", "零售价", "找货价格", "当期找货价格"])
    if not name_col or not market_col:
        return pd.DataFrame(columns=["商品", "行情价"])

    parsed = pd.DataFrame(
        {
            "商品": df[name_col].astype(str).str.strip(),
            "行情价": df[market_col].map(to_number),
        }
    )
    return parsed[parsed["商品"].ne("") & parsed["商品"].ne("合计")]


def parse_inventory_table(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_dataframe(raw_df, ["商品"])
    if df.empty:
        return pd.DataFrame(columns=["商品", "库存量"])

    name_col = find_column(df.columns, ["商品", "商品名称"])
    qty_col = find_column(df.columns, ["库存", "数量", "条数", "库存量"])
    if not name_col or not qty_col:
        return pd.DataFrame(columns=["商品", "库存量"])

    parsed = pd.DataFrame(
        {
            "商品": df[name_col].astype(str).str.strip(),
            "库存量": df[qty_col].map(to_number),
        }
    )
    parsed = parsed[parsed["商品"].ne("") & parsed["商品"].ne("合计")]
    parsed["库存量"] = pd.to_numeric(parsed["库存量"], errors="coerce").fillna(0.0)
    return parsed.groupby("商品", as_index=False).agg(库存量=("库存量", "sum"))


def parse_order_table(raw_df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_dataframe(raw_df, ["商品", "订单量"])
    if df.empty:
        return pd.DataFrame(columns=["商品", "指导零售价", "批发价", "订单量", "金额"])

    name_col = find_column(df.columns, ["商品", "商品名称"])
    guide_col = find_column(df.columns, ["建议零售价", "零售价"])
    wholesale_col = find_column(df.columns, ["批发价", "批发价格"])
    order_col = find_column(df.columns, ["订单量"])
    amount_col = find_column(df.columns, ["金额"])

    parsed = pd.DataFrame(
        {
            "商品": df[name_col].astype(str).str.strip() if name_col else "",
            "指导零售价": df[guide_col].map(to_number) if guide_col else None,
            "批发价": df[wholesale_col].map(to_number) if wholesale_col else None,
            "订单量": df[order_col].map(to_number) if order_col else None,
            "金额": df[amount_col].map(to_number) if amount_col else None,
        }
    )
    return parsed[parsed["商品"].ne("") & parsed["商品"].ne("合计")]


def parse_order_history_table(raw_df: pd.DataFrame, source_name: str = "") -> pd.DataFrame:
    parsed = parse_order_table(raw_df)
    if parsed.empty:
        return pd.DataFrame(
            columns=["商品", "指导零售价", "批发价", "订单量", "金额", "订单日期", "订单编号", "来源文件"]
        )

    metadata = extract_order_metadata(raw_df)
    parsed["订单日期"] = metadata["订单日期"]
    parsed["订单编号"] = metadata["订单编号"] or source_name
    parsed["来源文件"] = source_name
    return parsed


def extract_order_metadata(raw_df: pd.DataFrame) -> dict[str, Any]:
    order_date = None
    order_id = ""
    scan_rows = min(len(raw_df), 5)

    for row_idx in range(scan_rows):
        row = ["" if pd.isna(value) else str(value).strip() for value in raw_df.iloc[row_idx].tolist()]
        for idx, cell in enumerate(row):
            if cell == "订单日期" and idx + 1 < len(row):
                order_date = pd.to_datetime(row[idx + 1], errors="coerce")
            if cell == "订单编号" and idx + 1 < len(row):
                order_id = row[idx + 1]

    return {
        "订单日期": order_date.date() if not pd.isna(order_date) and order_date is not None else None,
        "订单编号": order_id,
    }


def merge_product_tables(price_df: pd.DataFrame, order_df: pd.DataFrame) -> pd.DataFrame:
    price_base = _collapse_by_product(price_df, ["指导零售价", "批发价", "行情价"])
    order_base = _collapse_by_product(order_df, ["指导零售价", "批发价", "订单量", "金额"])

    if price_base.empty and order_base.empty:
        return pd.DataFrame(
            columns=[
                "商品",
                "指导零售价",
                "行情价",
                "批发价",
                "订单量",
                "金额",
                "可订量",
                "分段",
            ]
        )

    if price_base.empty:
        grouped = order_base.copy()
    elif order_base.empty:
        grouped = price_base.copy()
    else:
        grouped = price_base.merge(order_base, on="商品", how="outer", suffixes=("_价表", "_订单"))
        grouped["指导零售价"] = grouped["指导零售价_订单"].combine_first(grouped["指导零售价_价表"])
        grouped["批发价"] = grouped["批发价_订单"].combine_first(grouped["批发价_价表"])
        grouped = grouped.drop(columns=["指导零售价_价表", "指导零售价_订单", "批发价_价表", "批发价_订单"])

    for column in ["订单量", "金额"]:
        if column not in grouped.columns:
            grouped[column] = pd.NA
    if "行情价" not in grouped.columns:
        grouped["行情价"] = pd.NA
    grouped["可订量"] = grouped["订单量"].fillna(0).astype(float)
    grouped["分段"] = grouped["指导零售价"].map(get_band_name)
    return grouped[
        ["商品", "指导零售价", "行情价", "批发价", "订单量", "金额", "可订量", "分段"]
    ].sort_values("商品", kind="stable")


def get_band_name(retail_price: Any) -> str:
    if retail_price is None or pd.isna(retail_price):
        return ""
    price = float(retail_price)
    for band in BAND_DEFINITIONS:
        if band["min"] <= price <= band["max"]:
            return band["name"]
    return "按档位投放"


def apply_price_overrides(products_df: pd.DataFrame, edited_df: pd.DataFrame) -> pd.DataFrame:
    df = products_df.copy()
    df["指导零售价"] = pd.to_numeric(df["指导零售价"], errors="coerce")
    df["行情价"] = pd.to_numeric(df["行情价"], errors="coerce")
    df["批发价"] = pd.to_numeric(df["批发价"], errors="coerce")
    if edited_df is not None and not edited_df.empty:
        editable = edited_df.copy()
        editable["指导零售价"] = pd.to_numeric(editable["指导零售价"], errors="coerce")
        editable["行情价"] = pd.to_numeric(editable["行情价"], errors="coerce")
        editable["批发价"] = pd.to_numeric(editable["批发价"], errors="coerce")
        editable["商品"] = editable["商品"].astype(str).str.strip()
        editable = editable[editable["商品"].ne("") & editable["商品"].ne("nan")]
        editable = editable.set_index("商品")
        for column in ["指导零售价", "批发价", "行情价"]:
            if column in editable.columns:
                df[column] = df["商品"].map(editable[column]).combine_first(df[column])

        new_names = [name for name in editable.index if name not in set(df["商品"])]
        if new_names:
            additions = editable.loc[new_names].reset_index()
            additions["订单量"] = pd.NA
            additions["金额"] = pd.NA
            additions["可订量"] = 0.0
            additions["分段"] = additions["指导零售价"].map(get_band_name)
            df = pd.concat([df, additions[df.columns]], ignore_index=True)

    df["分段"] = df["指导零售价"].map(get_band_name)
    effective_price = df["行情价"].combine_first(df["批发价"])
    df["单条毛利"] = effective_price.fillna(0) - df["批发价"].fillna(0)
    return df.sort_values("商品", kind="stable").reset_index(drop=True)


def compute_fill_scenarios(products_df: pd.DataFrame, config: Config) -> tuple[dict[str, float], pd.DataFrame]:
    candidates = expand_units(products_df, value_column="批发价")
    min_plan = build_plan(candidates, config, ascending=True, score_column="批发价")
    max_plan = build_plan(candidates, config, ascending=False, score_column="批发价")

    actual_qty = float(products_df["订单量"].fillna(0).sum())
    actual_amount = float(
        products_df["金额"].fillna(products_df["订单量"].fillna(0) * products_df["批发价"].fillna(0)).sum()
    )

    summary = {
        "目标总条数": config.target_total,
        "投放量": config.supply_total,
        "分段上限合计": sum(config.band_caps.values()),
        "可参与测算条数": len(candidates),
        "实际订单条数": actual_qty,
        "实际订单金额": actual_amount,
    }

    table = pd.DataFrame(
        [
            {
                "方案": "满档最低金额",
                "条数": min_plan["total_qty"],
                "金额": min_plan["total_value"],
                "说明": f"可订量不足，缺 {min_plan['shortage']} 条" if min_plan["shortage"] else "按最低成本凑满目标条数",
            },
            {
                "方案": "满档最高金额",
                "条数": max_plan["total_qty"],
                "金额": max_plan["total_value"],
                "说明": f"可订量不足，缺 {max_plan['shortage']} 条" if max_plan["shortage"] else "按最高成本凑满目标条数",
            },
            {
                "方案": "实际订单",
                "条数": actual_qty,
                "金额": actual_amount,
                "说明": "已达到目标条数" if actual_qty >= config.target_total else f"距离目标还差 {config.target_total - actual_qty:.0f} 条",
            },
        ]
    )
    return summary, table


def build_fill_plan_products(products_df: pd.DataFrame, config: Config, highest: bool = True) -> pd.DataFrame:
    candidates = expand_units(products_df, value_column="批发价")
    plan = build_plan(candidates, config, ascending=not highest, score_column="批发价")
    selected = pd.DataFrame(plan["selected_units"])
    if selected.empty:
        return pd.DataFrame(columns=["商品", "分段", "订单量", "批发价", "行情价", "金额"])

    grouped = (
        selected.groupby(["商品", "分段", "批发价", "行情价"], as_index=False, dropna=False)
        .agg(订单量=("商品", "count"))
        .sort_values(["订单量", "批发价", "商品"], ascending=[False, False, True], kind="stable")
    )
    grouped["行情价"] = pd.to_numeric(grouped["行情价"], errors="coerce").fillna(0.0)
    grouped["金额"] = grouped["订单量"] * grouped["批发价"]
    return grouped[["商品", "分段", "订单量", "批发价", "行情价", "金额"]]


def compute_optimization(products_df: pd.DataFrame, config: Config) -> tuple[dict[str, float], pd.DataFrame]:
    candidates = expand_units(products_df, value_column="单条毛利")
    plan = build_plan(candidates, config, ascending=False, score_column="单条毛利")
    selected = pd.DataFrame(plan["selected_units"])
    if selected.empty:
        summary = {"推荐条数": 0, "推荐金额": 0.0, "预估毛利": 0.0, "未满足条数": config.target_total}
        return summary, pd.DataFrame(columns=["商品", "分段", "批发价", "行情价", "推荐条数", "预估毛利"])

    grouped = selected.groupby(["商品", "分段", "批发价", "行情价"], as_index=False, dropna=False).agg(
        推荐条数=("商品", "count"), 预估毛利=("单条毛利", "sum")
    )
    grouped["行情价"] = pd.to_numeric(grouped["行情价"], errors="coerce").fillna(0.0)
    grouped["排序分组"] = grouped["分段"].map(BAND_DISPLAY_ORDER).fillna(999)
    grouped = grouped.sort_values(
        ["排序分组", "批发价", "行情价", "商品"],
        ascending=[True, False, False, True],
        kind="stable",
    ).drop(columns=["排序分组"])
    grouped["预估金额"] = grouped["推荐条数"] * grouped["批发价"]
    summary = {
        "推荐条数": float(len(selected)),
        "推荐金额": float(selected["批发价"].fillna(0).sum()),
        "预估毛利": float(selected["单条毛利"].fillna(0).sum()),
        "未满足条数": plan["shortage"],
    }
    return summary, grouped[["商品", "分段", "批发价", "行情价", "推荐条数", "预估毛利"]]


def build_optimization_plan_products(products_df: pd.DataFrame, config: Config) -> pd.DataFrame:
    candidates = expand_units(products_df, value_column="单条毛利")
    plan = build_plan(candidates, config, ascending=False, score_column="单条毛利")
    selected = pd.DataFrame(plan["selected_units"])
    if selected.empty:
        return pd.DataFrame(columns=["商品", "分段", "订单量", "批发价", "行情价", "金额", "预估毛利"])

    grouped = selected.groupby(["商品", "分段", "批发价", "行情价"], as_index=False, dropna=False).agg(
        订单量=("商品", "count"),
        预估毛利=("单条毛利", "sum"),
    )
    grouped["行情价"] = pd.to_numeric(grouped["行情价"], errors="coerce").fillna(0.0)
    grouped["金额"] = grouped["订单量"] * grouped["批发价"]
    grouped["排序分组"] = grouped["分段"].map(BAND_DISPLAY_ORDER).fillna(999)
    grouped = grouped.sort_values(
        ["排序分组", "批发价", "行情价", "商品"],
        ascending=[True, False, False, True],
        kind="stable",
    ).drop(columns=["排序分组"])
    return grouped[["商品", "分段", "订单量", "批发价", "行情价", "金额", "预估毛利"]]


def compare_plan_products(higher_plan_df: pd.DataFrame, lower_plan_df: pd.DataFrame) -> tuple[dict[str, float], pd.DataFrame]:
    higher = higher_plan_df.copy() if higher_plan_df is not None else pd.DataFrame()
    lower = lower_plan_df.copy() if lower_plan_df is not None else pd.DataFrame()
    if higher.empty:
        higher = pd.DataFrame(columns=["商品", "分段", "订单量", "批发价", "行情价", "金额"])
    if lower.empty:
        lower = pd.DataFrame(columns=["商品", "分段", "订单量", "批发价", "行情价", "金额"])

    higher_grouped = higher.groupby("商品", as_index=False, dropna=False).agg(
        分组=("分段", "last"),
        高档位上限=("订单量", "sum"),
        批发价=("批发价", "last"),
        行情价=("行情价", "last"),
    )
    lower_grouped = lower.groupby("商品", as_index=False, dropna=False).agg(低档位上限=("订单量", "sum"))
    merged = higher_grouped.merge(lower_grouped, on="商品", how="outer").fillna(0.0)
    merged["多出条数"] = merged["高档位上限"] - merged["低档位上限"]
    merged = merged[merged["多出条数"] > 0].copy()
    if merged.empty:
        summary = {"新增品种数": 0, "新增总条数": 0, "新增总成本": 0.0, "新增总毛利": 0.0}
        return summary, pd.DataFrame(columns=["分组", "商品名称", "高档位上限", "低档位上限", "多出条数", "批发价", "行情价", "新增成本", "新增毛利"])

    merged["商品名称"] = merged["商品"]
    merged["新增成本"] = merged["多出条数"] * pd.to_numeric(merged["批发价"], errors="coerce").fillna(0.0)
    merged["行情价"] = pd.to_numeric(merged["行情价"], errors="coerce")
    effective_price = merged["行情价"].combine_first(pd.to_numeric(merged["批发价"], errors="coerce"))
    merged["新增毛利"] = merged["多出条数"] * (effective_price.fillna(0.0) - pd.to_numeric(merged["批发价"], errors="coerce").fillna(0.0))
    result = merged[["分组", "商品名称", "高档位上限", "低档位上限", "多出条数", "批发价", "行情价", "新增成本", "新增毛利"]]
    result = result.sort_values(["多出条数", "新增毛利", "新增成本"], ascending=[False, False, False], kind="stable")
    summary = {
        "新增品种数": int(len(result)),
        "新增总条数": float(result["多出条数"].sum()),
        "新增总成本": float(result["新增成本"].sum()),
        "新增总毛利": float(result["新增毛利"].sum()),
    }
    return summary, result


def compute_profit_analysis(products_df: pd.DataFrame) -> tuple[dict[str, float], pd.DataFrame]:
    df = products_df.copy()
    df["订单量"] = df["订单量"].fillna(0)
    df["行情价"] = pd.to_numeric(df["行情价"], errors="coerce")
    effective_price = df["行情价"].combine_first(df["批发价"])
    df["单条毛利"] = effective_price.fillna(0) - df["批发价"].fillna(0)
    df["订单毛利"] = df["订单量"] * df["单条毛利"]

    order_df = df[df["订单量"] > 0].copy()
    summary = {
        "订单总条数": float(order_df["订单量"].sum()),
        "订单总成本": float((order_df["订单量"] * order_df["批发价"].fillna(0)).sum()),
        "订单总毛利": float(order_df["订单毛利"].sum()),
        "已录入行情价商品": int(order_df["行情价"].notna().sum()),
    }
    order_df = order_df.sort_values("订单毛利", ascending=False, kind="stable")
    return summary, order_df[["商品", "订单量", "批发价", "行情价", "单条毛利", "订单毛利"]]


def resolve_market_prices_for_orders(order_df: pd.DataFrame, market_history_df: pd.DataFrame) -> pd.DataFrame:
    df = order_df.copy()
    if df.empty:
        df["结算行情价"] = pd.NA
        return df

    if market_history_df is None or market_history_df.empty:
        df["结算行情价"] = pd.NA
        return df

    history = market_history_df.copy()
    history["商品"] = history["商品"].astype(str).str.strip()
    history["行情价"] = pd.to_numeric(history["行情价"], errors="coerce")
    history["生效日期"] = pd.to_datetime(history["生效日期"], errors="coerce").dt.date
    history = history.dropna(subset=["商品", "行情价", "生效日期"])
    if history.empty:
        df["结算行情价"] = pd.NA
        return df

    resolved_frames: list[pd.DataFrame] = []
    df["商品"] = df["商品"].astype(str).str.strip()
    if "订单日期" in df.columns:
        df["订单日期"] = pd.to_datetime(df["订单日期"], errors="coerce").dt.date
    else:
        df["订单日期"] = pd.NaT

    for product, group in df.groupby("商品", sort=False):
        product_history = history[history["商品"] == product].sort_values("生效日期", kind="stable")
        temp = group.copy()
        if product_history.empty:
            temp["结算行情价"] = pd.NA
            resolved_frames.append(temp)
            continue

        prices = []
        for _, row in temp.iterrows():
            order_date = row.get("订单日期")
            if pd.isna(order_date) or order_date is None:
                matched = product_history.iloc[-1]["行情价"]
            else:
                matched_rows = product_history[product_history["生效日期"] <= order_date]
                matched = matched_rows.iloc[-1]["行情价"] if not matched_rows.empty else product_history.iloc[0]["行情价"]
            prices.append(matched)
        temp["结算行情价"] = prices
        resolved_frames.append(temp)

    return pd.concat(resolved_frames, ignore_index=True)


def compute_cumulative_profit_tables(order_df: pd.DataFrame, market_history_df: pd.DataFrame) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    df = resolve_market_prices_for_orders(order_df, market_history_df)
    if df.empty:
        empty_product = pd.DataFrame(columns=["商品", "累计订货量", "累计订货金额", "累计利润", "最新结算行情价"])
        empty_order = pd.DataFrame(columns=["订单日期", "订单编号", "订单条数", "订单金额", "订单利润"])
        summary = {"累计总金额": 0.0, "累计总条数": 0.0, "累计总利润": 0.0, "累计总盈亏": 0.0}
        return summary, empty_product, empty_order

    df["订单量"] = pd.to_numeric(df["订单量"], errors="coerce").fillna(0.0)
    df["批发价"] = pd.to_numeric(df["批发价"], errors="coerce").fillna(0.0)
    df["金额"] = pd.to_numeric(df["金额"], errors="coerce").fillna(df["订单量"] * df["批发价"])
    df["结算行情价"] = pd.to_numeric(df["结算行情价"], errors="coerce")
    effective_price = df["结算行情价"].combine_first(df["批发价"])
    df["单条利润"] = effective_price.fillna(0) - df["批发价"]
    df["订单利润"] = df["单条利润"] * df["订单量"]

    product_table = (
        df.groupby("商品", as_index=False)
        .agg(
            累计订货量=("订单量", "sum"),
            累计订货金额=("金额", "sum"),
            累计利润=("订单利润", "sum"),
            最新结算行情价=("结算行情价", "last"),
        )
        .sort_values(["累计利润", "累计订货金额"], ascending=[False, False], kind="stable")
    )

    group_cols = [col for col in ["订单日期", "订单编号"] if col in df.columns]
    if group_cols:
        order_table = (
            df.groupby(group_cols, as_index=False)
            .agg(订单条数=("订单量", "sum"), 订单金额=("金额", "sum"), 订单利润=("订单利润", "sum"))
            .sort_values(group_cols, kind="stable")
        )
    else:
        order_table = pd.DataFrame(columns=["订单日期", "订单编号", "订单条数", "订单金额", "订单利润"])

    total_profit = float(df["订单利润"].sum())
    summary = {
        "累计总金额": float(df["金额"].sum()),
        "累计总条数": float(df["订单量"].sum()),
        "累计总利润": total_profit,
        "累计总盈亏": total_profit,
    }
    return summary, product_table, order_table


def compute_inventory_profit_table(inventory_df: pd.DataFrame, catalog_df: pd.DataFrame) -> tuple[dict[str, float], pd.DataFrame]:
    if inventory_df is None or inventory_df.empty:
        summary = {"库存总条数": 0.0, "库存总市值": 0.0, "库存总成本": 0.0, "库存总盈亏": 0.0}
        return summary, pd.DataFrame(columns=["商品", "库存量", "批发价", "行情价", "库存成本", "库存市值", "库存盈亏"])

    merged = inventory_df.merge(
        catalog_df[["商品", "批发价", "行情价"]].copy(),
        on="商品",
        how="left",
    )
    merged["库存量"] = pd.to_numeric(merged["库存量"], errors="coerce").fillna(0.0)
    merged["批发价"] = pd.to_numeric(merged["批发价"], errors="coerce").fillna(0.0)
    merged["行情价"] = pd.to_numeric(merged["行情价"], errors="coerce").fillna(0.0)
    merged["库存成本"] = merged["库存量"] * merged["批发价"]
    merged["库存市值"] = merged["库存量"] * merged["行情价"]
    merged["库存盈亏"] = merged["库存市值"] - merged["库存成本"]
    merged = merged.sort_values(["库存市值", "库存量"], ascending=[False, False], kind="stable")

    summary = {
        "库存总条数": float(merged["库存量"].sum()),
        "库存总市值": float(merged["库存市值"].sum()),
        "库存总成本": float(merged["库存成本"].sum()),
        "库存总盈亏": float(merged["库存盈亏"].sum()),
    }
    return summary, merged[["商品", "库存量", "批发价", "行情价", "库存成本", "库存市值", "库存盈亏"]]


def aggregate_order_history(history_df: pd.DataFrame, start_date: date | None, end_date: date | None) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    if history_df is None or history_df.empty:
        empty_orders = pd.DataFrame(columns=["订单日期", "订单编号", "来源文件", "总条数", "总金额"])
        empty_products = pd.DataFrame(columns=["商品", "累计条数", "累计金额", "平均批发价", "平均指导零售价"])
        summary = {"订单次数": 0, "累计条数": 0.0, "累计金额": 0.0, "覆盖商品数": 0}
        return summary, empty_orders, empty_products

    df = history_df.copy()
    if start_date:
        df = df[df["订单日期"] >= start_date]
    if end_date:
        df = df[df["订单日期"] <= end_date]

    if df.empty:
        empty_orders = pd.DataFrame(columns=["订单日期", "订单编号", "来源文件", "总条数", "总金额"])
        empty_products = pd.DataFrame(columns=["商品", "累计条数", "累计金额", "平均批发价", "平均指导零售价"])
        summary = {"订单次数": 0, "累计条数": 0.0, "累计金额": 0.0, "覆盖商品数": 0}
        return summary, empty_orders, empty_products

    df["订单量"] = df["订单量"].fillna(0)
    df["金额"] = df["金额"].fillna(df["订单量"] * df["批发价"].fillna(0))

    order_summary = (
        df.groupby(["订单日期", "订单编号", "来源文件"], as_index=False)
        .agg(总条数=("订单量", "sum"), 总金额=("金额", "sum"))
        .sort_values(["订单日期", "订单编号"], ascending=[True, True], kind="stable")
    )

    product_summary = (
        df.groupby("商品", as_index=False)
        .agg(
            累计条数=("订单量", "sum"),
            累计金额=("金额", "sum"),
            平均批发价=("批发价", "mean"),
            平均指导零售价=("指导零售价", "mean"),
        )
        .sort_values(["累计条数", "累计金额"], ascending=[False, False], kind="stable")
    )

    summary = {
        "订单次数": int(len(order_summary)),
        "累计条数": float(df["订单量"].sum()),
        "累计金额": float(df["金额"].sum()),
        "覆盖商品数": int(df["商品"].nunique()),
    }
    return summary, order_summary, product_summary


def compare_multiple_configs(
    products_df: pd.DataFrame,
    configs: list[tuple[str, str, Config]],
    rules_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for name, preset_id, raw_config in configs:
        tier_df = products_df.copy()
        config = Config(
            target_total=int(raw_config.target_total),
            supply_total=int(raw_config.supply_total),
            band_caps=dict(raw_config.band_caps),
        )

        if rules_df is not None and not rules_df.empty:
            tier_df, period_summary = apply_period_rules(tier_df, rules_df, preset_id)
            if "可订货量合计" in period_summary:
                config.target_total = int(period_summary["可订货量合计"])
            if "投放量" in period_summary:
                config.supply_total = int(period_summary["投放量"])
            if period_summary.get("band_caps"):
                config.band_caps.update(period_summary["band_caps"])

        actual_qty = float(tier_df["订单量"].fillna(0).sum())
        actual_amount = float(
            tier_df["金额"].fillna(tier_df["订单量"].fillna(0) * tier_df["批发价"].fillna(0)).sum()
        )

        fill_summary, fill_table = compute_fill_scenarios(tier_df, config)
        opt_summary, _ = compute_optimization(tier_df, config)
        min_amount = _pick_plan_amount(fill_table, "满档最低金额")
        max_amount = _pick_plan_amount(fill_table, "满档最高金额")
        profit_amount = opt_summary["推荐金额"]
        rows.append(
            {
                "档位": name,
                "目标总条数": config.target_total,
                "投放量": config.supply_total,
                "分段上限合计": sum(config.band_caps.values()),
                "按最低金额凑满": min_amount,
                "按最高金额凑满": max_amount,
                "按最多利润推荐条数": opt_summary["推荐条数"],
                "按最多利润金额": profit_amount,
                "按最多利润毛利": opt_summary["预估毛利"],
                "距当前订单条数差": actual_qty - config.target_total,
            }
        )

    return pd.DataFrame(rows).sort_values(["目标总条数", "档位"], ascending=[False, True], kind="stable")


def expand_units(products_df: pd.DataFrame, value_column: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for _, row in products_df.iterrows():
        qty = int(max(row.get("可订量") or 0, 0))
        band_name = row.get("分段") or ""
        if not qty or not band_name:
            continue
        for _ in range(qty):
            units.append(
                {
                    "商品": row["商品"],
                    "分段": band_name,
                    "批发价": float(row.get("批发价") or 0),
                    "行情价": float(row.get("行情价") or 0),
                    "单条毛利": float(row.get("单条毛利") or 0),
                    value_column: float(row.get(value_column) or 0),
                }
            )
    return units


def build_plan(candidates: list[dict[str, Any]], config: Config, ascending: bool, score_column: str) -> dict[str, Any]:
    effective_caps = dict(config.band_caps)
    effective_caps.setdefault("按档位投放", max(config.target_total, config.supply_total, len(candidates)))
    band_counts = {band: 0 for band in effective_caps}
    selected: list[dict[str, Any]] = []

    sorted_candidates = sorted(
        candidates,
        key=lambda item: (item.get(score_column, 0), item.get("商品", "")),
        reverse=not ascending,
    )
    for unit in sorted_candidates:
        if len(selected) >= config.target_total:
            break
        band_name = unit["分段"]
        if band_name not in effective_caps:
            effective_caps[band_name] = max(config.target_total, config.supply_total, len(candidates))
            band_counts.setdefault(band_name, 0)
        if band_counts.get(band_name, 0) >= effective_caps.get(band_name, 0):
            continue
        selected.append(unit)
        band_counts[band_name] = band_counts.get(band_name, 0) + 1

    total_value = sum(item.get("批发价", 0) if score_column == "单条毛利" else item.get(score_column, 0) for item in selected)
    return {
        "selected_units": selected,
        "total_qty": len(selected),
        "total_value": total_value,
        "shortage": max(config.target_total - len(selected), 0),
    }


def _collapse_by_product(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["商品", *columns])
    result = df[["商品", *[col for col in columns if col in df.columns]]].copy()
    return result.groupby("商品", as_index=False).max()


def merge_price_catalog(catalog_df: pd.DataFrame, imported_price_df: pd.DataFrame, order_df: pd.DataFrame) -> pd.DataFrame:
    catalog_base = _collapse_by_product(catalog_df, ["指导零售价", "批发价", "行情价"])
    imported_base = _collapse_by_product(imported_price_df, ["指导零售价", "批发价"])
    if not catalog_base.empty and not imported_base.empty:
        price_base = catalog_base.merge(imported_base, on="商品", how="outer", suffixes=("_库", "_导入"))
        price_base["指导零售价"] = price_base["指导零售价_导入"].combine_first(price_base["指导零售价_库"])
        price_base["批发价"] = price_base["批发价_导入"].combine_first(price_base["批发价_库"])
        price_base["行情价"] = price_base["行情价"]
        price_base = price_base.drop(columns=["指导零售价_库", "指导零售价_导入", "批发价_库", "批发价_导入"])
    elif not imported_base.empty:
        price_base = imported_base.copy()
        price_base["行情价"] = pd.NA
    else:
        price_base = catalog_base.copy()

    return merge_product_tables(price_base, order_df)


def _pick_plan_amount(fill_table: pd.DataFrame, plan_name: str) -> float:
    matched = fill_table.loc[fill_table["方案"] == plan_name, "金额"]
    if matched.empty:
        return 0.0
    return float(matched.iloc[0])
