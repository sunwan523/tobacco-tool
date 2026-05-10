from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

import pandas as pd


TIER_COLUMNS = [
    "三十档",
    "二十九档",
    "二十八档",
    "二十七档",
    "二十六档",
    "二十五档",
    "二十四档",
    "二十三档",
    "二十二档",
    "二十一档",
    "二十档",
    "十九档",
    "十八档",
    "十七档",
    "十六档",
    "十五档",
    "十四档",
    "十三档",
    "十二档",
    "十一档",
    "十档",
    "九档",
    "八档",
    "七档",
    "六档",
    "五档",
    "四档",
    "三档",
    "二档",
    "一档",
]

SEGMENT_ORDER = [
    "1-3段",
    "4-5段",
    "6段",
    "7段",
    "8-9段",
    "10段",
    "11段",
    "12段",
    "13段",
    "14-15段",
]

IGNORED_SEGMENTS = {"二次自选", "二次自选价位段"}
SECONDARY_CHOICE_KEYWORD = "二次自选"
NON_SEGMENT_LABELS = {"按档位投放"}
INVENTORY_HEADERS = ["库存量", "库存", "实际库存", "当前库存", "可用库存", "数量", "库存数量(大)", "库存数量（大）"]
CIGAR_KEYWORDS = ("雪茄", "王冠", "长城", "泰山(3G", "泰山（3G")


@dataclass(frozen=True)
class ParsedWorkbook:
    orders: pd.DataFrame
    prices: pd.DataFrame
    strategy_items: pd.DataFrame
    segment_limits: pd.DataFrame
    tier_totals: pd.DataFrame


@dataclass(frozen=True)
class TierPlan:
    tier_name: str
    strategy: str
    line_items: pd.DataFrame
    total_qty: int
    total_cost: float
    total_market_value: float
    total_profit: float
    non_segment_qty: int
    segment_qty: int
    unmet_segment_limit: int
    target_total_qty: int | None


def load_workbooks(
    order_file: BinaryIO,
    strategy_file: BinaryIO,
    prices: pd.DataFrame,
) -> ParsedWorkbook:
    orders = parse_orders(order_file)
    strategy_items, segment_limits, tier_totals = parse_strategy(strategy_file)
    return ParsedWorkbook(
        orders=orders,
        prices=prices.copy(),
        strategy_items=strategy_items,
        segment_limits=segment_limits,
        tier_totals=tier_totals,
    )


def parse_orders(file_obj: BinaryIO) -> pd.DataFrame:
    raw = pd.read_excel(BytesIO(file_obj.getvalue()), header=None)
    header_idx = locate_header_row(raw, ["商品", "批发价", "订单量"])
    data = normalize_header_frame(raw, header_idx)
    data = data.rename(
        columns={
            "商品": "商品名称",
            "订单量": "订单量",
            "批发价": "批发价",
            "建议零售价": "建议零售价",
            "盒码": "盒码",
            "条码": "条码",
        }
    )
    data = data[data["商品名称"].notna()].copy()
    data["商品名称"] = data["商品名称"].astype(str).str.strip()
    data = data[~data["商品名称"].isin(["合计", "商品名称"])].copy()
    data["订单量"] = to_numeric(data.get("订单量")).fillna(0)
    data["批发价"] = to_numeric(data.get("批发价"))
    data["建议零售价"] = to_numeric(data.get("建议零售价"))
    for column in ["盒码", "条码"]:
        if column in data.columns:
            data[column] = data[column].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    keep_cols = [col for col in ["商品名称", "批发价", "订单量", "建议零售价", "盒码", "条码"] if col in data.columns]
    return (
        data[keep_cols]
        .groupby("商品名称", as_index=False)
        .agg(
            {
                "批发价": "max",
                "订单量": "sum",
                "建议零售价": "max",
                "盒码": "first",
                "条码": "first",
            }
        )
        .sort_values(["订单量", "商品名称"], ascending=[False, True])
        .reset_index(drop=True)
    )


def parse_prices(file_obj: BinaryIO) -> pd.DataFrame:
    data = pd.read_excel(BytesIO(file_obj.getvalue()))
    data.columns = [normalize_text(col) for col in data.columns]
    rename_map = {
        "商品": "商品名称",
        "建议零售价": "建议零售价",
        "批发价": "批发价",
        "当期找货价格": "当期找货价格",
        "盒码": "盒码",
        "条码": "条码",
    }
    data = data.rename(columns=rename_map)
    data = data[data["商品名称"].notna()].copy()
    data["商品名称"] = data["商品名称"].astype(str).str.strip()
    for column in ["建议零售价", "批发价", "当期找货价格"]:
        if column in data.columns:
            data[column] = to_numeric(data[column])
    for column in ["盒码", "条码"]:
        if column in data.columns:
            data[column] = data[column].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    keep_cols = [col for col in ["商品名称", "建议零售价", "批发价", "当期找货价格", "盒码", "条码"] if col in data.columns]
    return (
        data[keep_cols]
        .groupby("商品名称", as_index=False)
        .agg(
            {
                "建议零售价": "max",
                "批发价": "max",
                "当期找货价格": "max",
                "盒码": "first",
                "条码": "first",
            }
        )
        .reset_index(drop=True)
    )


def parse_inventory(file_obj: BinaryIO) -> pd.DataFrame:
    raw = pd.read_excel(BytesIO(file_obj.getvalue()), header=None)
    header_idx = locate_header_row(raw, ["商品"])
    data = normalize_header_frame(raw, header_idx)
    quantity_col = next((col for col in data.columns if normalize_text(col) in INVENTORY_HEADERS), None)
    if quantity_col is None:
        quantity_col = next((col for col in data.columns if "库存" in normalize_text(col)), None)
    if quantity_col is None:
        raise ValueError("库存表中未找到库存数量列。")
    rename_map = {
        "商品": "商品名称",
        "商品名称": "商品名称",
        "盒码": "盒码",
        "条码": "条码",
        "商品条码": "条码",
        "进货价": "批发价",
        "卷烟编码": "商品编码",
        quantity_col: "库存量",
    }
    data = data.rename(columns=rename_map)
    data = data[data["商品名称"].notna()].copy()
    data["商品名称"] = data["商品名称"].astype(str).str.strip()
    data["库存量"] = to_numeric(data["库存量"]).fillna(0)
    if "批发价" in data.columns:
        data["批发价"] = to_numeric(data["批发价"])
    for column in ["盒码", "条码"]:
        if column in data.columns:
            data[column] = data[column].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    keep_cols = [col for col in ["商品名称", "库存量", "盒码", "条码", "批发价", "商品编码"] if col in data.columns]
    agg_map: dict[str, str] = {"库存量": "sum"}
    for column, method in [("盒码", "first"), ("条码", "first"), ("批发价", "max"), ("商品编码", "first")]:
        if column in data[keep_cols].columns:
            agg_map[column] = method
    return data[keep_cols].groupby("商品名称", as_index=False).agg(agg_map).reset_index(drop=True)


def parse_strategy(file_obj: BinaryIO) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = pd.read_excel(BytesIO(file_obj.getvalue()), sheet_name=0, header=None)
    raw = trim_sparse_frame(raw)
    header_idx = locate_header_row(raw, ["价位段", "商品名称", "三十档"])
    data = normalize_header_frame(raw, header_idx)
    data.columns = [normalize_text(col) for col in data.columns]
    data = data.rename(
        columns={
            "价位段": "价位段",
            "价位段 ": "价位段",
            "商品编码": "商品编码",
            "商品名称": "商品名称",
        }
    )
    for column in ["价位段", "商品编码", "商品名称"]:
        if column not in data.columns:
            data[column] = ""

    for tier in TIER_COLUMNS:
        if tier in data.columns:
            data[tier] = to_numeric(data[tier]).fillna(0)

    data["价位段"] = data["价位段"].map(normalize_segment_label)
    data["商品名称"] = data["商品名称"].map(normalize_text)
    secondary_choice_mask = is_secondary_choice_row(data)
    control_mask = is_strategy_control_row(data)

    total_rows = data[data["商品名称"].astype(str).str.contains("可订货量合计", na=False)].copy()
    if total_rows.empty:
        raise ValueError("订货量表中未找到“可订货量合计”行。")
    tier_totals = pd.DataFrame(
        {
            "档位": TIER_COLUMNS,
            "可订货量合计": [int(to_numeric(total_rows.iloc[0].get(tier)).fillna(0).iloc[0]) for tier in TIER_COLUMNS],
        }
    )

    limit_rows = data[control_mask].copy()
    segment_limits = build_segment_limits(limit_rows)

    item_mask = data["商品名称"].notna() & data["商品名称"].ne("")
    item_mask &= ~data["商品名称"].astype(str).str.contains("价位段总量上限|可订货量合计", na=False)
    item_mask &= ~control_mask
    item_mask &= ~secondary_choice_mask
    strategy_items = data.loc[
        item_mask,
        ["价位段", "商品编码", "商品名称", *[tier for tier in TIER_COLUMNS if tier in data.columns]],
    ].copy()
    strategy_items = strategy_items.reset_index(drop=True)
    return strategy_items, segment_limits, tier_totals


def build_analysis_dataset(parsed: ParsedWorkbook) -> pd.DataFrame:
    orders = ensure_order_columns(parsed.orders)

    # 如果有投放表，使用投放表作为基础
    if not parsed.strategy_items.empty:
        base = enrich_with_price_lookup(parsed.strategy_items, parsed.prices)
    else:
        # 如果没有投放表，使用订单表作为基础
        base = orders.copy()
        # 添加必要的列
        if "价位段" not in base.columns:
            base["价位段"] = ""
        if "商品编码" not in base.columns:
            base["商品编码"] = ""
        base = enrich_with_price_lookup(base, parsed.prices)
    
    base = base.merge(
        orders[["商品名称", "订单量", "批发价"]].rename(columns={"批发价": "订单批发价"}),
        on="商品名称",
        how="left",
    )
    base["订单量"] = to_numeric(base.get("订单量")).fillna(0)
    base["价格库批发价"] = to_numeric(base.get("价格库批发价"))
    base["订单批发价"] = to_numeric(base.get("订单批发价"))
    base["批发价"] = base["价格库批发价"].fillna(base["订单批发价"])
    base["建议零售价"] = to_numeric(base.get("建议零售价"))
    base["当期找货价格"] = to_numeric(base.get("当期找货价格"))
    base["有效销售价"] = base["当期找货价格"].fillna(base["批发价"])
    base["单条毛利"] = base["有效销售价"] - base["批发价"]
    base["是否价位段"] = ~base["价位段"].isin(IGNORED_SEGMENTS) & ~base["价位段"].isin(NON_SEGMENT_LABELS)
    for column in ["盒码", "条码"]:
        if column in base.columns:
            base[column] = base[column].astype(str).replace("nan", "")
    return base


def build_inventory_dataset(inventory: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    inventory = inventory.copy()
    if "批发价" in inventory.columns:
        inventory = inventory.rename(columns={"批发价": "库存批发价"})
    result = enrich_with_price_lookup(inventory, prices)
    result["库存量"] = to_numeric(result["库存量"]).fillna(0)
    result["库存批发价"] = to_numeric(result.get("库存批发价"))
    result["价格库批发价"] = to_numeric(result.get("价格库批发价"))
    result["批发价"] = result["价格库批发价"].fillna(result["库存批发价"])
    result["建议零售价"] = to_numeric(result.get("建议零售价"))
    result["当期找货价格"] = to_numeric(result.get("当期找货价格"))
    result["有效销售价"] = result["当期找货价格"].fillna(result["批发价"])
    result["库存成本"] = result["库存量"] * result["批发价"].fillna(0)
    result["库存市值"] = result["库存量"] * result["有效销售价"].fillna(0)
    result["库存盈亏"] = result["库存市值"] - result["库存成本"]
    return result


def compute_missing_market_prices(inventory_data: pd.DataFrame) -> pd.DataFrame:
    missing = inventory_data[(inventory_data["库存量"] > 0) & (inventory_data["当期找货价格"].isna())].copy()
    cols = [col for col in ["商品名称", "库存量", "批发价", "建议零售价", "盒码", "条码", "当期找货价格"] if col in missing.columns]
    return missing[cols].reset_index(drop=True)


def compute_missing_order_market_prices(order_data: pd.DataFrame) -> pd.DataFrame:
    missing = order_data[(order_data["订单量"] > 0) & (order_data["当期找货价格"].isna())].copy()
    cols = [col for col in ["商品名称", "订单量", "批发价", "建议零售价", "盒码", "条码", "当期找货价格"] if col in missing.columns]
    return missing[cols].drop_duplicates(subset=["商品名称"]).reset_index(drop=True)


def build_order_price_check_dataset(orders: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    result = enrich_with_price_lookup(orders, prices)
    result["订单量"] = to_numeric(result.get("订单量")).fillna(0)
    result["价格库批发价"] = to_numeric(result.get("价格库批发价"))
    result["订单批发价"] = to_numeric(result.get("批发价"))
    result["批发价"] = result["价格库批发价"].fillna(result["订单批发价"])
    result["建议零售价"] = to_numeric(result.get("建议零售价"))
    result["当期找货价格"] = to_numeric(result.get("当期找货价格"))
    return result


def enrich_with_price_lookup(items: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    result = items.copy()
    price_cols = [col for col in ["商品名称", "建议零售价", "批发价", "当期找货价格", "盒码", "条码"] if col in prices.columns]
    lookup = prices[price_cols].copy()

    if "商品名称" in result.columns:
        name_map = lookup.dropna(subset=["商品名称"]).drop_duplicates(subset=["商品名称"], keep="last").set_index("商品名称")
        apply_lookup_map(result, name_map, "商品名称")

    if "条码" in result.columns and "条码" in lookup.columns:
        barcode_map = lookup[lookup["条码"].notna() & (lookup["条码"].astype(str).str.strip() != "")]
        barcode_map = barcode_map.drop_duplicates(subset=["条码"], keep="last").set_index("条码")
        apply_lookup_map(result, barcode_map, "条码")

    if "盒码" in result.columns and "盒码" in lookup.columns:
        box_map = lookup[lookup["盒码"].notna() & (lookup["盒码"].astype(str).str.strip() != "")]
        box_map = box_map.drop_duplicates(subset=["盒码"], keep="last").set_index("盒码")
        apply_lookup_map(result, box_map, "盒码")

    if "批发价" in result.columns and "价格库批发价" not in result.columns:
        result = result.rename(columns={"批发价": "价格库批发价"})
    return result


def apply_lookup_map(result: pd.DataFrame, lookup_map: pd.DataFrame, key_col: str) -> None:
    for source_col in ["建议零售价", "批发价", "当期找货价格", "盒码", "条码"]:
        if source_col not in lookup_map.columns:
            continue
        mapped = result[key_col].map(lookup_map[source_col]) if key_col in result.columns else pd.Series(index=result.index, dtype="object")
        if source_col not in result.columns:
            result[source_col] = mapped
        else:
            result[source_col] = result[source_col].where(~result[source_col].isna() & (result[source_col].astype(str) != ""), mapped)


def infer_current_tier(order_total_qty: int, tier_totals: pd.DataFrame) -> tuple[str, str]:
    match = tier_totals[tier_totals["可订货量合计"] == order_total_qty]
    if not match.empty:
        return str(match.iloc[0]["档位"]), "按订单总条数与“可订货量合计”精确匹配"
    tier_totals = tier_totals.copy()
    tier_totals["距离"] = (tier_totals["可订货量合计"] - order_total_qty).abs()
    best = tier_totals.sort_values(["距离", "可订货量合计"], ascending=[True, True]).iloc[0]
    return str(best["档位"]), "未精确匹配，按最接近的“可订货量合计”推断"


def get_previous_tier(current_tier: str) -> str | None:
    index = TIER_COLUMNS.index(current_tier)
    if index == len(TIER_COLUMNS) - 1:
        return None
    return TIER_COLUMNS[index + 1]


def get_higher_tier(current_tier: str) -> str | None:
    index = TIER_COLUMNS.index(current_tier)
    if index == 0:
        return None
    return TIER_COLUMNS[index - 1]


def compute_order_profit(data: pd.DataFrame) -> pd.DataFrame:
    result = data[data["订单量"] > 0].copy()
    result["订单成本"] = result["订单量"] * result["批发价"]
    result["订单估值"] = result["订单量"] * result["有效销售价"]
    result["订单盈亏"] = result["订单量"] * result["单条毛利"]
    return result.sort_values(["订单盈亏", "订单成本"], ascending=[False, False]).reset_index(drop=True)


def compute_inventory_profit(inventory_data: pd.DataFrame) -> pd.DataFrame:
    return inventory_data[inventory_data["库存量"] > 0].sort_values(["库存市值", "库存量"], ascending=[False, False]).reset_index(drop=True)


def get_tier_total_qty(tier_totals: pd.DataFrame, tier_name: str) -> int | None:
    if tier_totals is None or tier_totals.empty:
        return None
    match = tier_totals.loc[tier_totals["档位"] == tier_name, "可订货量合计"]
    if match.empty:
        return None
    value = to_numeric(match).fillna(0).iloc[0]
    return int(value) if value > 0 else None


def get_segment_limit(segment_limits: pd.DataFrame, segment: str, tier_name: str, segment_items: pd.DataFrame) -> int:
    fallback = int(to_numeric(segment_items["档位可订量"]).fillna(0).sum())
    if segment_limits is None or segment_limits.empty or tier_name not in segment_limits.columns:
        return fallback

    limit_row = segment_limits[segment_limits["价位段"] == segment]
    if limit_row.empty:
        return fallback

    limit_value = to_numeric(limit_row.iloc[0].get(tier_name)).fillna(0).iloc[0]
    if limit_value <= 0:
        return fallback
    return min(int(limit_value), fallback)


def limit_plan_total_qty(line_items: pd.DataFrame, max_total_qty: int | None, strategy: str) -> pd.DataFrame:
    if max_total_qty is None or line_items.empty:
        return line_items

    result = line_items.copy()
    result["计划量"] = to_numeric(result["计划量"]).fillna(0).astype(int)
    overflow = int(result["计划量"].sum()) - int(max_total_qty)
    if overflow <= 0:
        return result

    if strategy == "cost":
        sort_columns = ["批发价", "商品名称"]
    else:
        sort_columns = ["单条毛利", "有效销售价", "商品名称"]

    for idx in result.sort_values(sort_columns, ascending=[True] * len(sort_columns)).index:
        if overflow <= 0:
            break
        qty = int(result.at[idx, "计划量"])
        remove_qty = min(qty, overflow)
        result.at[idx, "计划量"] = qty - remove_qty
        overflow -= remove_qty

    return result[result["计划量"] > 0].reset_index(drop=True)


def compute_tier_plan(
    data: pd.DataFrame,
    segment_limits: pd.DataFrame,
    tier_name: str,
    strategy: str,
    max_total_qty: int | None = None,
) -> TierPlan:
    if strategy not in {"cost", "profit"}:
        raise ValueError("strategy 仅支持 cost 或 profit")

    tier_items = ensure_plan_columns(data, tier_name)
    tier_items = tier_items.rename(columns={tier_name: "档位可订量"})
    tier_items["档位可订量"] = to_numeric(tier_items["档位可订量"]).fillna(0).astype(int)
    tier_items["批发价"] = to_numeric(tier_items["批发价"])
    tier_items["有效销售价"] = to_numeric(tier_items["有效销售价"])
    tier_items["单条毛利"] = to_numeric(tier_items["单条毛利"])
    tier_items = tier_items[tier_items["档位可订量"] > 0].copy()
    tier_items["批发价排序"] = tier_items["批发价"].fillna(-1)
    tier_items["有效销售价"] = tier_items["有效销售价"].fillna(tier_items["批发价"])
    tier_items["单条毛利"] = tier_items["单条毛利"].fillna(tier_items["有效销售价"] - tier_items["批发价"])
    tier_items["单条毛利排序"] = tier_items["单条毛利"].fillna(-10**9)

    allocations: list[pd.DataFrame] = []
    non_segment = tier_items[tier_items["价位段"].isin(NON_SEGMENT_LABELS)].copy()
    if not non_segment.empty:
        non_segment["计划量"] = non_segment["档位可订量"]
        non_segment["来源"] = "按档位投放全量"
        allocations.append(non_segment)

    unmet_segment_limit = 0
    # 收集所有在tier_items中出现的段位（排除非段位标签和被忽略的段位）
    all_segments = tier_items[
        (~tier_items["价位段"].isin(NON_SEGMENT_LABELS)) & 
        (~tier_items["价位段"].isin(IGNORED_SEGMENTS))
    ]["价位段"].unique().tolist()
    
    # 遍历所有段位
    for segment in all_segments:
        segment_items = tier_items[tier_items["价位段"] == segment].copy()
        if segment_items.empty:
            continue
        segment_limit = get_segment_limit(segment_limits, segment, tier_name, segment_items)
        picks, remaining = allocate_segment(segment_items, segment_limit, strategy)
        unmet_segment_limit += remaining
        if not picks.empty:
            picks["来源"] = f"{segment}{'最贵满订' if strategy == 'cost' else '利润优先满订'}"
            allocations.append(picks)

    if allocations:
        line_items = pd.concat(allocations, ignore_index=True)
    else:
        line_items = pd.DataFrame(columns=["价位段", "商品名称", "批发价", "有效销售价", "单条毛利", "盒码", "条码", "档位可订量", "计划量", "来源"])

    line_items = limit_plan_total_qty(line_items, max_total_qty, strategy)
    line_items["计划成本"] = line_items["计划量"] * line_items["批发价"].fillna(0)
    line_items["计划市值"] = line_items["计划量"] * line_items["有效销售价"].fillna(line_items["批发价"]).fillna(0)
    line_items["计划盈亏"] = line_items["计划量"] * line_items["单条毛利"].fillna(0)

    return TierPlan(
        tier_name=tier_name,
        strategy=strategy,
        line_items=line_items.sort_values(["价位段", "计划成本", "商品名称"], ascending=[True, False, True]).reset_index(drop=True),
        total_qty=int(line_items["计划量"].sum()) if not line_items.empty else 0,
        total_cost=float(line_items["计划成本"].sum()) if not line_items.empty else 0.0,
        total_market_value=float(line_items["计划市值"].sum()) if not line_items.empty else 0.0,
        total_profit=float(line_items["计划盈亏"].sum()) if not line_items.empty else 0.0,
        non_segment_qty=int(line_items.loc[line_items["价位段"].isin(NON_SEGMENT_LABELS), "计划量"].sum()) if not line_items.empty else 0,
        segment_qty=int(line_items.loc[(~line_items["价位段"].isin(NON_SEGMENT_LABELS)) & (~line_items["价位段"].isin(IGNORED_SEGMENTS)), "计划量"].sum()) if not line_items.empty else 0,
        unmet_segment_limit=int(unmet_segment_limit),
        target_total_qty=max_total_qty if max_total_qty is not None else int((line_items["计划量"].sum() if not line_items.empty else 0) + unmet_segment_limit),
    )


def compute_dual_strategy_summary(data: pd.DataFrame, segment_limits: pd.DataFrame, tier_totals: pd.DataFrame) -> pd.DataFrame:
    records = []
    for tier in TIER_COLUMNS:
        max_total_qty = get_tier_total_qty(tier_totals, tier)
        cost_plan = compute_tier_plan(data, segment_limits, tier, "cost", max_total_qty)
        profit_plan = compute_tier_plan(data, segment_limits, tier, "profit", max_total_qty)
        records.append(
            {
                "档位": tier,
                "策略表可订货量合计": int(tier_totals.loc[tier_totals["档位"] == tier, "可订货量合计"].iloc[0]),
                "最贵满订条数": cost_plan.total_qty,
                "最贵满订金额": cost_plan.total_cost,
                "最贵满订盈亏": cost_plan.total_profit,
                "利润优先满订条数": profit_plan.total_qty,
                "利润优先满订金额": profit_plan.total_cost,
                "利润优先满订盈亏": profit_plan.total_profit,
            }
        )
    return pd.DataFrame(records)


def compare_plan_with_order(plan: TierPlan, data: pd.DataFrame) -> pd.DataFrame:
    actual = data[["商品名称", "价位段", "批发价", "有效销售价", "订单量"]].copy()
    diff = plan.line_items[["商品名称", "价位段", "计划量", "批发价", "有效销售价"]].merge(
        actual,
        on=["商品名称", "价位段", "批发价", "有效销售价"],
        how="outer",
    )
    diff["计划量"] = to_numeric(diff.get("计划量")).fillna(0).astype(int)
    diff["订单量"] = to_numeric(diff.get("订单量")).fillna(0).astype(int)
    diff["差异量"] = diff["计划量"] - diff["订单量"]
    diff["差异成本"] = diff["差异量"] * diff["批发价"]
    diff["差异估值"] = diff["差异量"] * diff["有效销售价"]
    return diff[diff["差异量"] != 0].sort_values(["差异成本", "商品名称"], ascending=[False, True]).reset_index(drop=True)


def compute_tier_diff(data: pd.DataFrame, high_tier: str, low_tier: str) -> pd.DataFrame:
    diff = data[["价位段", "商品名称", "批发价", "有效销售价", "单条毛利", high_tier, low_tier]].copy()
    diff = diff.rename(columns={high_tier: "高档位可订量", low_tier: "低档位可订量"})
    diff["高档位可订量"] = to_numeric(diff["高档位可订量"]).fillna(0).astype(int)
    diff["低档位可订量"] = to_numeric(diff["低档位可订量"]).fillna(0).astype(int)
    diff["新增量"] = diff["高档位可订量"] - diff["低档位可订量"]
    diff = diff[diff["新增量"] > 0].copy()
    diff["新增成本"] = diff["新增量"] * diff["批发价"]
    diff["新增估值"] = diff["新增量"] * diff["有效销售价"]
    diff["新增盈亏"] = diff["新增量"] * diff["单条毛利"]
    return diff.sort_values(["新增成本", "新增量", "商品名称"], ascending=[False, False, True]).reset_index(drop=True)


def recommend_profit_plan(
    data: pd.DataFrame,
    segment_limits: pd.DataFrame,
    tier_name: str,
    tier_totals: pd.DataFrame | None = None,
) -> TierPlan | None:
    compare_tier = get_previous_tier(tier_name)
    if compare_tier is None:
        return None

    target_plan = compute_tier_plan(data, segment_limits, compare_tier, "cost", get_tier_total_qty(tier_totals, compare_tier))
    profit_full_plan = compute_tier_plan(data, segment_limits, tier_name, "profit", get_tier_total_qty(tier_totals, tier_name))
    max_qty = profit_full_plan.total_qty  # 本档位最高可订数量
    
    # 准备商品数据
    tier_items = ensure_plan_columns(data, tier_name)
    tier_items = tier_items.rename(columns={tier_name: "档位可订量"})
    tier_items["档位可订量"] = to_numeric(tier_items["档位可订量"]).fillna(0).astype(int)
    tier_items["批发价"] = to_numeric(tier_items["批发价"]).fillna(0)
    tier_items["有效销售价"] = to_numeric(tier_items["有效销售价"]).fillna(tier_items["批发价"])
    tier_items["单条毛利"] = to_numeric(tier_items["单条毛利"]).fillna(tier_items["有效销售价"] - tier_items["批发价"]).fillna(0)
    tier_items = tier_items[tier_items["档位可订量"] > 0].copy()
    
    # 步骤1：先用下一档位订满的数量做最优订货
    def build_base_plan_with_target_qty() -> TierPlan:
        full_plan = compute_tier_plan(data, segment_limits, tier_name, "profit", get_tier_total_qty(tier_totals, tier_name))
        
        if target_plan.total_qty >= full_plan.total_qty:
            return full_plan
        
        need_remove = full_plan.total_qty - target_plan.total_qty
        
        line_items = full_plan.line_items.copy()
        line_items["批发价"] = to_numeric(line_items["批发价"]).fillna(0)
        line_items["有效销售价"] = to_numeric(line_items["有效销售价"]).fillna(line_items["批发价"])
        line_items["单条毛利"] = to_numeric(line_items["单条毛利"]).fillna(line_items["有效销售价"] - line_items["批发价"]).fillna(0)
        line_items["计划量"] = to_numeric(line_items["计划量"]).fillna(0).astype(int)
        
        candidates = line_items[line_items["计划量"] > 0].copy()
        candidates = candidates.sort_values(["单条毛利", "批发价", "商品名称"], ascending=[True, False, True]).reset_index()
        
        removed = 0
        for _, candidate in candidates.iterrows():
            if removed >= need_remove:
                break
            
            for idx, row in line_items.iterrows():
                if row["商品名称"] == candidate["商品名称"] and row["价位段"] == candidate["价位段"]:
                    if line_items.at[idx, "计划量"] > 0:
                        line_items.at[idx, "计划量"] = int(line_items.at[idx, "计划量"]) - 1
                        removed += 1
                        break
        
        line_items = line_items[line_items["计划量"] > 0].copy().reset_index(drop=True)
        line_items["计划成本"] = line_items["计划量"] * line_items["批发价"].fillna(0)
        line_items["计划市值"] = line_items["计划量"] * line_items["有效销售价"].fillna(line_items["批发价"]).fillna(0)
        line_items["计划盈亏"] = line_items["计划量"] * line_items["单条毛利"].fillna(0)
        
        return TierPlan(
            tier_name=tier_name,
            strategy=f"profit-base-{target_plan.total_qty}",
            line_items=line_items.sort_values(["价位段", "计划成本", "商品名称"], ascending=[True, False, True]).reset_index(drop=True),
            total_qty=int(line_items["计划量"].sum()) if not line_items.empty else 0,
            total_cost=float(line_items["计划成本"].sum()) if not line_items.empty else 0.0,
            total_market_value=float(line_items["计划市值"].sum()) if not line_items.empty else 0.0,
            total_profit=float(line_items["计划盈亏"].sum()) if not line_items.empty else 0.0,
            non_segment_qty=int(line_items.loc[line_items["价位段"].isin(NON_SEGMENT_LABELS), "计划量"].sum()) if not line_items.empty else 0,
            segment_qty=int(line_items.loc[(~line_items["价位段"].isin(NON_SEGMENT_LABELS)) & (~line_items["价位段"].isin(IGNORED_SEGMENTS)), "计划量"].sum()) if not line_items.empty else 0,
            unmet_segment_limit=0,
            target_total_qty=int(line_items["计划量"].sum()) if not line_items.empty else 0,
        )
    
    base_plan = build_base_plan_with_target_qty()
    
    # 检查基数方案是否已经满足条件
    if base_plan.total_cost > target_plan.total_cost:
        return base_plan
    
    # 步骤2：把还可以加购的卷烟按利润降序逐条增加
    current_line_items = base_plan.line_items.copy()
    
    # 构建已选数量映射
    selected_map = {}
    segment_qty_map = {}
    for _, row in current_line_items.iterrows():
        key = (row["商品名称"], row["价位段"])
        selected_map[key] = int(row["计划量"])
        seg = row["价位段"]
        segment_qty_map[seg] = segment_qty_map.get(seg, 0) + int(row["计划量"])
    
    # 收集所有可增加的商品候选
    add_candidates = []
    for _, row in tier_items.iterrows():
        key = (row["商品名称"], row["价位段"])
        current_selected = selected_map.get(key, 0)
        max_qty_item = int(row["档位可订量"])
        seg = row["价位段"]
        
        if current_selected < max_qty_item:
            add_candidates.append(row)
    
    # 按单条毛利降序排序
    if not add_candidates:
        add_candidates_df = pd.DataFrame(columns=tier_items.columns)
    else:
        add_candidates_df = pd.DataFrame(add_candidates)
        add_candidates_df = add_candidates_df.sort_values(["单条毛利", "批发价", "商品名称"], ascending=[False, False, True])
    
    for _, candidate in add_candidates_df.iterrows():
        # 检查是否满足保档条件
        current_line_items["计划成本"] = current_line_items["计划量"] * current_line_items["批发价"].fillna(0)
        current_total_cost = float(current_line_items["计划成本"].sum()) if not current_line_items.empty else 0.0
        current_total_qty = int(current_line_items["计划量"].sum()) if not current_line_items.empty else 0
        
        if current_total_cost > target_plan.total_cost:
            current_line_items["计划市值"] = current_line_items["计划量"] * current_line_items["有效销售价"].fillna(current_line_items["批发价"]).fillna(0)
            current_line_items["计划盈亏"] = current_line_items["计划量"] * current_line_items["单条毛利"].fillna(0)
            return TierPlan(
                tier_name=tier_name,
                strategy=f"profit-added-over-{compare_tier}",
                line_items=current_line_items.sort_values(["价位段", "计划成本", "商品名称"], ascending=[True, False, True]).reset_index(drop=True),
                total_qty=current_total_qty,
                total_cost=current_total_cost,
                total_market_value=float(current_line_items["计划市值"].sum()) if not current_line_items.empty else 0.0,
                total_profit=float(current_line_items["计划盈亏"].sum()) if not current_line_items.empty else 0.0,
                non_segment_qty=int(current_line_items.loc[current_line_items["价位段"].isin(NON_SEGMENT_LABELS), "计划量"].sum()) if not current_line_items.empty else 0,
                segment_qty=int(current_line_items.loc[(~current_line_items["价位段"].isin(NON_SEGMENT_LABELS)) & (~current_line_items["价位段"].isin(IGNORED_SEGMENTS)), "计划量"].sum()) if not current_line_items.empty else 0,
                unmet_segment_limit=0,
                target_total_qty=current_total_qty,
            )
        
        # 检查是否已经达到本档位最高可订数量
        if current_total_qty >= max_qty:
            break
        
        # 检查分段位上限
        seg = candidate["价位段"]
        if seg not in NON_SEGMENT_LABELS and seg not in IGNORED_SEGMENTS:
            limit_row = segment_limits[segment_limits["价位段"] == seg]
            if not limit_row.empty:
                seg_limit = int(limit_row.iloc[0][tier_name])
                current_seg_qty = segment_qty_map.get(seg, 0)
                if current_seg_qty >= seg_limit:
                    continue
        
        # 增加这条商品
        key = (candidate["商品名称"], candidate["价位段"])
        found = False
        for idx, row in current_line_items.iterrows():
            if row["商品名称"] == candidate["商品名称"] and row["价位段"] == candidate["价位段"]:
                current_line_items.at[idx, "计划量"] = int(current_line_items.at[idx, "计划量"]) + 1
                found = True
                break
        
        if not found:
            new_item = candidate.copy()
            new_item["计划量"] = 1
            new_item["来源"] = "增加保档"
            current_line_items = pd.concat([current_line_items, pd.DataFrame([new_item])], ignore_index=True)
        
        selected_map[key] = selected_map.get(key, 0) + 1
        segment_qty_map[seg] = segment_qty_map.get(seg, 0) + 1
    
    # 步骤3：极端情况，已经增加到最高数量还没超过，进行价位段内的调整
    # 先重新调整，构建新的方案
    def rebuild_plan() -> pd.DataFrame:
        new_items_list = []
        
        # 处理所有段位和按档位投放
        all_segments = SEGMENT_ORDER.copy() + list(NON_SEGMENT_LABELS)
        
        for segment in all_segments:
            # 获取该段位的所有商品
            segment_all_items = tier_items[tier_items["价位段"] == segment].copy()
            if segment_all_items.empty:
                continue
            
            # 排序：先按单条毛利降序，利润相同按批发价降序
            segment_sorted = segment_all_items.sort_values(["单条毛利", "批发价", "商品名称"], ascending=[False, False, True])
            
            # 计算该段位应该选多少条
            seg_current = current_line_items[current_line_items["价位段"] == segment].copy()
            seg_total_qty = int(seg_current["计划量"].sum()) if not seg_current.empty else 0
            
            if seg_total_qty <= 0:
                continue
            
            remaining = seg_total_qty
            for _, item in segment_sorted.iterrows():
                if remaining <= 0:
                    break
                
                max_qty_item = int(item["档位可订量"])
                select_qty = min(max_qty_item, remaining)
                
                if select_qty > 0:
                    new_item = item.copy()
                    new_item["计划量"] = select_qty
                    new_item["来源"] = f"{segment}重选"
                    new_items_list.append(new_item)
                    remaining -= select_qty
        
        return pd.DataFrame(new_items_list) if new_items_list else current_line_items
    
    new_line_items = rebuild_plan()
    new_line_items["计划成本"] = new_line_items["计划量"] * new_line_items["批发价"].fillna(0)
    new_line_items["计划市值"] = new_line_items["计划量"] * new_line_items["有效销售价"].fillna(new_line_items["批发价"]).fillna(0)
    new_line_items["计划盈亏"] = new_line_items["计划量"] * new_line_items["单条毛利"].fillna(0)
    
    new_total_qty = int(new_line_items["计划量"].sum()) if not new_line_items.empty else 0
    new_total_cost = float(new_line_items["计划成本"].sum()) if not new_line_items.empty else 0.0
    
    if new_total_cost > target_plan.total_cost:
        return TierPlan(
            tier_name=tier_name,
            strategy=f"profit-rebuilt-over-{compare_tier}",
            line_items=new_line_items.sort_values(["价位段", "计划成本", "商品名称"], ascending=[True, False, True]).reset_index(drop=True),
            total_qty=new_total_qty,
            total_cost=new_total_cost,
            total_market_value=float(new_line_items["计划市值"].sum()) if not new_line_items.empty else 0.0,
            total_profit=float(new_line_items["计划盈亏"].sum()) if not new_line_items.empty else 0.0,
            non_segment_qty=int(new_line_items.loc[new_line_items["价位段"].isin(NON_SEGMENT_LABELS), "计划量"].sum()) if not new_line_items.empty else 0,
            segment_qty=int(new_line_items.loc[(~new_line_items["价位段"].isin(NON_SEGMENT_LABELS)) & (~new_line_items["价位段"].isin(IGNORED_SEGMENTS)), "计划量"].sum()) if not new_line_items.empty else 0,
            unmet_segment_limit=0,
            target_total_qty=new_total_qty,
        )
    
    return None


def recommend_thirty_profit_plan(data: pd.DataFrame, segment_limits: pd.DataFrame) -> TierPlan | None:
    return recommend_profit_plan(data, segment_limits, "三十档")


def compute_profit_recommendation_summary(
    data: pd.DataFrame,
    segment_limits: pd.DataFrame,
    tier_totals: pd.DataFrame | None = None,
) -> pd.DataFrame:
    records = []
    for tier in TIER_COLUMNS:
        compare_tier = get_previous_tier(tier)
        profit_plan = compute_tier_plan(data, segment_limits, tier, "profit", get_tier_total_qty(tier_totals, tier))
        recommendation = recommend_profit_plan(data, segment_limits, tier, tier_totals)
        next_cost_plan = compute_tier_plan(data, segment_limits, compare_tier, "cost", get_tier_total_qty(tier_totals, compare_tier)) if compare_tier else None

        records.append(
            {
                "档位": tier,
                "对比下一档": compare_tier,
                "推荐条数": recommendation.total_qty if recommendation else pd.NA,
                "推荐金额": recommendation.total_cost if recommendation else pd.NA,
                "推荐盈亏": recommendation.total_profit if recommendation else pd.NA,
                "利润优先满订条数": profit_plan.total_qty,
                "利润优先满订金额": profit_plan.total_cost,
                "利润优先满订盈亏": profit_plan.total_profit,
                "较利润优先满订条数差": (recommendation.total_qty - profit_plan.total_qty) if recommendation else pd.NA,
                "较利润优先满订金额差": (recommendation.total_cost - profit_plan.total_cost) if recommendation else pd.NA,
                "较利润优先满订盈亏差": (recommendation.total_profit - profit_plan.total_profit) if recommendation else pd.NA,
                "较下一档最贵满订多条数": (recommendation.total_qty - next_cost_plan.total_qty) if recommendation and next_cost_plan else pd.NA,
                "较下一档最贵满订多金额": (recommendation.total_cost - next_cost_plan.total_cost) if recommendation and next_cost_plan else pd.NA,
            }
        )
    return pd.DataFrame(records)


def allocate_segment(segment_items: pd.DataFrame, segment_limit: int, strategy: str) -> tuple[pd.DataFrame, int]:
    if strategy == "cost":
        sorted_items = segment_items.sort_values(["批发价排序", "商品名称"], ascending=[False, True])
    else:
        sorted_items = segment_items.sort_values(["单条毛利排序", "有效销售价", "商品名称"], ascending=[False, False, True])

    remaining = max(segment_limit, 0)
    picks: list[pd.Series] = []
    for _, row in sorted_items.iterrows():
        if remaining <= 0:
            break
        qty = min(int(row["档位可订量"]), remaining)
        if qty <= 0:
            continue
        picked = row.copy()
        picked["计划量"] = qty
        picks.append(picked)
        remaining -= qty
    if picks:
        return pd.DataFrame(picks), remaining
    return pd.DataFrame(columns=[*segment_items.columns, "计划量"]), remaining


def build_segment_frontier(segment_items: pd.DataFrame, tier_name: str, segment_limit: int) -> list[tuple[int, int, dict[str, int]]]:
    items = segment_items.copy()
    items["cap"] = to_numeric(items[tier_name]).fillna(0).astype(int)
    items["批发价"] = to_numeric(items["批发价"])
    items["单条毛利"] = to_numeric(items["单条毛利"])
    items = items[items["cap"] > 0].reset_index(drop=True)
    items["批发价"] = items["批发价"].fillna(0)
    items["单条毛利"] = items["单条毛利"].fillna(0)
    states: list[dict[int, tuple[int, dict[str, int]]]] = [dict() for _ in range(segment_limit + 1)]
    states[0][0] = (0, {})

    for _, row in items.iterrows():
        cost_int = int(round(float(row["批发价"]) * 100))
        profit_int = int(round(float(row["单条毛利"]) * 100))
        cap = int(row["cap"])
        name = str(row["商品名称"])
        next_states = [dict(bucket) for bucket in states]
        for qty in range(segment_limit + 1):
            for total_cost, (total_profit, selection) in states[qty].items():
                max_add = min(cap, segment_limit - qty)
                for add_qty in range(1, max_add + 1):
                    new_qty = qty + add_qty
                    new_cost = total_cost + cost_int * add_qty
                    new_profit = total_profit + profit_int * add_qty
                    new_selection = dict(selection)
                    new_selection[name] = add_qty
                    prev = next_states[new_qty].get(new_cost)
                    if prev is None or new_profit > prev[0]:
                        next_states[new_qty][new_cost] = (new_profit, new_selection)
        states = [prune_profit_dict(bucket) for bucket in next_states]

    frontier = []
    for cost_int, (profit_int, selection) in prune_profit_dict(states[segment_limit]).items():
        frontier.append((cost_int, profit_int, selection))
    return frontier


def prune_profit_dict(bucket: dict[int, tuple[int, dict[str, int]]]) -> dict[int, tuple[int, dict[str, int]]]:
    best_profit = -10**18
    pruned: dict[int, tuple[int, dict[str, int]]] = {}
    for cost_int in sorted(bucket.keys()):
        profit_int, selection = bucket[cost_int]
        if profit_int > best_profit:
            pruned[cost_int] = (profit_int, selection)
            best_profit = profit_int
    return pruned


def prune_cost_states(states: dict[int, tuple[int, dict[str, dict[str, int]]]]) -> dict[int, tuple[int, dict[str, dict[str, int]]]]:
    best_profit = -10**18
    pruned: dict[int, tuple[int, dict[str, dict[str, int]]]] = {}
    for cost_int in sorted(states.keys()):
        profit_int, selection = states[cost_int]
        if profit_int > best_profit:
            pruned[cost_int] = (profit_int, selection)
            best_profit = profit_int
    return pruned


def locate_header_row(raw: pd.DataFrame, required_labels: list[str]) -> int:
    for idx, row in raw.iterrows():
        labels = {normalize_text(value) for value in row.tolist() if normalize_text(value)}
        if all(any(req in label for label in labels) for req in required_labels):
            return int(idx)
    raise ValueError(f"未找到表头，要求包含：{', '.join(required_labels)}")


def normalize_header_frame(raw: pd.DataFrame, header_idx: int) -> pd.DataFrame:
    headers = [normalize_text(value) or f"未命名列{index}" for index, value in enumerate(raw.iloc[header_idx].tolist())]
    data = raw.iloc[header_idx + 1 :].copy()
    data.columns = headers
    empty_unnamed_columns = [
        column for column in data.columns
        if str(column).startswith("未命名列") and data[column].isna().all()
    ]
    data = data.drop(columns=empty_unnamed_columns)
    data = data.dropna(axis=0, how="all")
    return data.reset_index(drop=True)


def normalize_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return (
        text.replace("\u3000", " ")
        .replace("—", "-")
        .replace("–", "-")
        .replace("－", "-")
        .replace("─", "-")
        .strip()
    )


def normalize_segment_label(value: object) -> str:
    text = normalize_text(value).replace("价位段", "").replace(" ", "")
    if text in {"", "nan"}:
        return ""
    return text


def is_secondary_choice_row(data: pd.DataFrame) -> pd.Series:
    if data.empty:
        return pd.Series(False, index=data.index)
    text_cells = data.map(normalize_text)
    return text_cells.apply(lambda row: any(SECONDARY_CHOICE_KEYWORD in value for value in row), axis=1)


def is_strategy_control_row(data: pd.DataFrame) -> pd.Series:
    if data.empty:
        return pd.Series(False, index=data.index)

    product_names = data.get("商品名称", pd.Series("", index=data.index)).map(normalize_segment_label)
    segments = data.get("价位段", pd.Series("", index=data.index)).map(normalize_segment_label)
    product_codes = data.get("商品编码", pd.Series("", index=data.index)).map(normalize_text)
    control_labels = set(SEGMENT_ORDER) | IGNORED_SEGMENTS

    explicit_limit = data.get("商品名称", pd.Series("", index=data.index)).astype(str).str.contains("价位段总量上限", na=False)
    named_control = product_names.isin(control_labels)
    segment_only_control = product_names.eq("") & product_codes.eq("") & segments.isin(control_labels)
    return explicit_limit | named_control | segment_only_control


def build_segment_limits(limit_rows: pd.DataFrame) -> pd.DataFrame:
    tier_columns = [tier for tier in TIER_COLUMNS if tier in limit_rows.columns]
    columns = ["价位段", *tier_columns]
    if limit_rows.empty:
        return pd.DataFrame(columns=columns)

    result = limit_rows.copy()
    result["价位段"] = result.apply(get_control_segment_label, axis=1)
    result = result[result["价位段"].ne("")]
    result = result[~result["价位段"].isin(IGNORED_SEGMENTS)]
    result = result[result[tier_columns].apply(lambda row: to_numeric(row).fillna(0).sum() > 0, axis=1)]
    if result.empty:
        return pd.DataFrame(columns=columns)
    return result[columns].reset_index(drop=True)


def get_control_segment_label(row: pd.Series) -> str:
    product_name = normalize_segment_label(row.get("商品名称"))
    segment = normalize_segment_label(row.get("价位段"))
    if product_name in set(SEGMENT_ORDER) | IGNORED_SEGMENTS:
        return product_name
    return segment


def trim_sparse_frame(raw: pd.DataFrame) -> pd.DataFrame:
    return raw.dropna(axis=1, how="all").dropna(axis=0, how="all").reset_index(drop=True)


def ensure_order_columns(orders: pd.DataFrame) -> pd.DataFrame:
    result = orders.copy() if orders is not None else pd.DataFrame()
    for column in ["商品名称", "订单量", "批发价"]:
        if column not in result.columns:
            result[column] = pd.Series(dtype="object")
    return result


def ensure_plan_columns(data: pd.DataFrame, tier_name: str) -> pd.DataFrame:
    result = data.copy()
    required = ["价位段", "商品名称", "批发价", "有效销售价", "单条毛利", "盒码", "条码", tier_name]
    for column in required:
        if column not in result.columns:
            result[column] = pd.Series(dtype="object")
    return result[required].copy()


def to_numeric(series_or_value: object) -> pd.Series:
    if isinstance(series_or_value, pd.Series):
        return pd.to_numeric(series_or_value, errors="coerce")
    return pd.to_numeric(pd.Series([series_or_value]), errors="coerce")


def is_cigar_product(name: object) -> bool:
    text = normalize_text(name)
    return any(keyword in text for keyword in CIGAR_KEYWORDS)
