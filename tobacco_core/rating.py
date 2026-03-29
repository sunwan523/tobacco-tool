from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path

import pandas as pd


DEFAULT_CUSTOMER_NAME = "曲靖市麒麟区梦回唐朝图文店"
DEFAULT_RESULT_PATH = Path(__file__).resolve().parent.parent / "data" / "rating_result_20260327.xlsx"

WEIGHTS = {
    "购进量得分": 30.0,
    "购进金额得分": 50.0,
    "条均价得分": 10.0,
    "一二类烟量占比得分": 5.0,
    "一二类烟金额得分": 5.0,
}

TIER_PERCENTAGES = [
    ("三十档", 1.0),
    ("二十九档", 2.0),
    ("二十八档", 2.0),
    ("二十七档", 2.0),
    ("二十六档", 2.0),
    ("二十五档", 3.0),
    ("二十四档", 3.0),
    ("二十三档", 4.0),
    ("二十二档", 4.0),
    ("二十一档", 4.0),
    ("二十档", 4.0),
    ("十九档", 4.0),
    ("十八档", 5.0),
    ("十七档", 5.0),
    ("十六档", 5.0),
    ("十五档", 5.0),
    ("十四档", 5.0),
    ("十三档", 5.0),
    ("十二档", 4.0),
    ("十一档", 4.0),
    ("十档", 4.0),
    ("九档", 4.0),
    ("八档", 4.0),
    ("七档", 3.0),
    ("六档", 3.0),
    ("五档", 2.5),
    ("四档", 2.0),
    ("三档", 2.0),
    ("二档", 2.0),
    ("一档", 0.5),
]


@dataclass
class RatingBenchmarks:
    quantity_max: float
    amount_max: float
    avg_price_max: float
    class12_ratio_max: float
    class12_amount_max: float


def load_rating_results(file_obj=None) -> pd.DataFrame:
    if file_obj is not None:
        return pd.read_excel(file_obj)
    if DEFAULT_RESULT_PATH.exists():
        return pd.read_excel(DEFAULT_RESULT_PATH)
    return pd.DataFrame(columns=["分公司", "客户经理", "专卖证号", "客户名称", "测算档位", "测算前档位"])


def find_customer_result(results_df: pd.DataFrame, customer_name: str = DEFAULT_CUSTOMER_NAME) -> pd.DataFrame:
    if results_df is None or results_df.empty or "客户名称" not in results_df.columns:
        return pd.DataFrame(columns=["分公司", "客户经理", "专卖证号", "客户名称", "测算档位", "测算前档位"])
    mask = results_df["客户名称"].astype(str).str.contains(customer_name, regex=False, na=False)
    return results_df.loc[mask].copy()


def build_tier_quota_table(total_customers: int) -> pd.DataFrame:
    rows = []
    running_upper = 0
    for tier_name, percent in TIER_PERCENTAGES:
        tier_count = ceil(total_customers * percent / 100) if total_customers > 0 else 0
        rank_start = running_upper + 1 if tier_count else 0
        rank_end = running_upper + tier_count if tier_count else 0
        rows.append(
            {
                "档位": tier_name,
                "参考占比%": percent,
                "预计客户数": tier_count,
                "预计排名区间": f"{rank_start}-{rank_end}" if tier_count else "-",
            }
        )
        running_upper = rank_end
    return pd.DataFrame(rows)


def compute_rating_metrics(
    history_df: pd.DataFrame | None,
    current_df: pd.DataFrame | None,
    qty_column: str = "订单量",
    amount_column: str = "金额",
    retail_column: str = "行情价",
    wholesale_column: str = "批发价",
    class12_threshold: float = 130.0,
) -> dict[str, float]:
    frames: list[pd.DataFrame] = []
    for df in [history_df, current_df]:
        if df is None or df.empty:
            continue
        temp = df.copy()
        for col in [qty_column, amount_column, retail_column, wholesale_column]:
            if col not in temp.columns:
                temp[col] = pd.NA
        if retail_column not in temp.columns or temp[retail_column].isna().all():
            if "行情价" in temp.columns and not temp["行情价"].isna().all():
                temp[retail_column] = temp["行情价"]
            elif "指导零售价" in temp.columns:
                temp[retail_column] = temp["指导零售价"]
        temp[qty_column] = pd.to_numeric(temp[qty_column], errors="coerce").fillna(0.0)
        temp[amount_column] = pd.to_numeric(temp[amount_column], errors="coerce")
        temp[wholesale_column] = pd.to_numeric(temp[wholesale_column], errors="coerce").fillna(0.0)
        temp[retail_column] = pd.to_numeric(temp[retail_column], errors="coerce").fillna(0.0)
        temp[amount_column] = temp[amount_column].fillna(temp[qty_column] * temp[wholesale_column])
        frames.append(temp[[qty_column, amount_column, retail_column, wholesale_column]])

    if not frames:
        return {
            "购进量": 0.0,
            "购进金额": 0.0,
            "条均价": 0.0,
            "一二类烟购进量": 0.0,
            "一二类烟购进量占比": 0.0,
            "一二类烟购进金额": 0.0,
        }

    merged = pd.concat(frames, ignore_index=True)
    total_qty = float(merged[qty_column].sum())
    total_amount = float(merged[amount_column].sum())
    class12_mask = merged[retail_column].fillna(0) >= class12_threshold
    class12_qty = float(merged.loc[class12_mask, qty_column].sum())
    class12_amount = float(merged.loc[class12_mask, amount_column].sum())
    avg_price = total_amount / total_qty if total_qty else 0.0
    class12_ratio = class12_qty / total_qty if total_qty else 0.0
    return {
        "购进量": total_qty,
        "购进金额": total_amount,
        "条均价": avg_price,
        "一二类烟购进量": class12_qty,
        "一二类烟购进量占比": class12_ratio,
        "一二类烟购进金额": class12_amount,
    }


def compute_rating_scores(metrics: dict[str, float], benchmarks: RatingBenchmarks) -> tuple[dict[str, float], pd.DataFrame]:
    benchmark_map = {
        "购进量得分": benchmarks.quantity_max,
        "购进金额得分": benchmarks.amount_max,
        "条均价得分": benchmarks.avg_price_max,
        "一二类烟量占比得分": benchmarks.class12_ratio_max,
        "一二类烟金额得分": benchmarks.class12_amount_max,
    }
    metric_map = {
        "购进量得分": metrics["购进量"],
        "购进金额得分": metrics["购进金额"],
        "条均价得分": metrics["条均价"],
        "一二类烟量占比得分": metrics["一二类烟购进量占比"],
        "一二类烟金额得分": metrics["一二类烟购进金额"],
    }

    rows = []
    total_score = 0.0
    for label, weight in WEIGHTS.items():
        benchmark = float(benchmark_map.get(label, 0) or 0)
        actual = float(metric_map.get(label, 0) or 0)
        score = 0.0 if benchmark <= 0 else min(actual / benchmark, 1.0) * weight
        total_score += score
        rows.append(
            {
                "评分维度": label,
                "你的值": actual,
                "参考最高值": benchmark,
                "权重分值": weight,
                "参考得分": score,
            }
        )

    summary = {
        "参考综合得分": total_score,
        "购进量": metrics["购进量"],
        "购进金额": metrics["购进金额"],
        "条均价": metrics["条均价"],
        "一二类烟量占比": metrics["一二类烟购进量占比"],
        "一二类烟金额": metrics["一二类烟购进金额"],
    }
    return summary, pd.DataFrame(rows)
