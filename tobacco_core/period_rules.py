from __future__ import annotations

from pathlib import Path

import pandas as pd

TIER_COLUMN_MAP = {
    "tier30": "三十档",
    "tier29": "二十九档",
    "tier28": "二十八档",
    "tier27": "二十七档",
    "tier26": "二十六档",
}

SAMPLE_RULE_PATH = Path(__file__).resolve().parent.parent / "data" / "period_rules_sample_202603.csv"


def load_period_rules(file_obj=None) -> pd.DataFrame:
    if file_obj is not None:
        name = getattr(file_obj, "name", "").lower()
        if name.endswith(".csv"):
            return normalize_period_rules(pd.read_csv(file_obj))
        return normalize_period_rules(pd.read_excel(file_obj))
    if SAMPLE_RULE_PATH.exists():
        return normalize_period_rules(pd.read_csv(SAMPLE_RULE_PATH))
    return pd.DataFrame()


def apply_period_rules(products_df: pd.DataFrame, rules_df: pd.DataFrame, preset_id: str) -> tuple[pd.DataFrame, dict]:
    if rules_df is None or rules_df.empty:
        return products_df.copy(), {}

    tier_column = TIER_COLUMN_MAP.get(preset_id)
    if not tier_column or tier_column not in rules_df.columns:
        return products_df.copy(), {}

    df = products_df.copy()
    df["本期上限"] = pd.NA
    df["规则分组"] = pd.NA

    product_rules = rules_df[rules_df["类型"] == "商品"].copy()
    # 过滤掉二次自行段位的商品
    product_rules = product_rules[~product_rules["分组"].str.contains("二次", na=False)]
    product_rules = product_rules[~product_rules["分组"].str.contains("自选", na=False)]
    product_rules[tier_column] = pd.to_numeric(product_rules[tier_column], errors="coerce")
    product_map = product_rules.set_index("商品名称")[tier_column].dropna().to_dict()
    group_map = product_rules.set_index("商品名称")["分组"].to_dict()
    df["本期上限"] = df["商品"].map(product_map)
    df["规则分组"] = df["商品"].map(group_map)
    df["分段"] = df["规则分组"].combine_first(df["分段"])
    # 有本期规则时，只允许规则表中出现的商品参与本期测算；未命中的商品本期可订量记为 0。
    df["可订量"] = df["本期上限"].fillna(0)

    summary_rules = rules_df[(rules_df["类型"] == "汇总") & rules_df["商品名称"].isin(["可订货量合计", "投放量"])].copy()
    summary_rules[tier_column] = pd.to_numeric(summary_rules[tier_column], errors="coerce")
    summary = {row["商品名称"]: float(row[tier_column]) for _, row in summary_rules.iterrows() if pd.notna(row[tier_column])}
    
    # 计算非二次自行段位的商品总条数
    if tier_column in product_rules.columns:
        non_secondary_total = product_rules[tier_column].fillna(0).sum()
        summary["可订货量合计"] = non_secondary_total

    band_rules = rules_df[(rules_df["类型"] == "分段上限") & (rules_df["商品名称"] == "价位段总量上限")].copy()
    # 过滤掉二次自行段位的分段上限
    band_rules = band_rules[~band_rules["分组"].str.contains("二次", na=False)]
    band_rules = band_rules[~band_rules["分组"].str.contains("自选", na=False)]
    band_rules[tier_column] = pd.to_numeric(band_rules[tier_column], errors="coerce")
    summary["band_caps"] = {row["分组"]: int(row[tier_column]) for _, row in band_rules.iterrows() if pd.notna(row[tier_column])}

    return df, summary


def build_tier_difference(products_df: pd.DataFrame, rules_df: pd.DataFrame, higher_tier_id: str, lower_tier_id: str) -> tuple[dict, pd.DataFrame]:
    if rules_df is None or rules_df.empty:
        summary = {"新增品种数": 0, "新增总条数": 0, "新增总成本": 0.0, "新增总毛利": 0.0}
        return summary, pd.DataFrame(columns=["分组", "商品名称", "高档位上限", "低档位上限", "多出条数", "批发价", "行情价", "新增成本", "新增毛利"])

    higher_col = TIER_COLUMN_MAP.get(higher_tier_id)
    lower_col = TIER_COLUMN_MAP.get(lower_tier_id)
    if not higher_col or not lower_col or higher_col not in rules_df.columns or lower_col not in rules_df.columns:
        summary = {"新增品种数": 0, "新增总条数": 0, "新增总成本": 0.0, "新增总毛利": 0.0}
        return summary, pd.DataFrame(columns=["分组", "商品名称", "高档位上限", "低档位上限", "多出条数", "批发价", "行情价", "新增成本", "新增毛利"])

    product_rules = rules_df[rules_df["类型"] == "商品"].copy()
    product_rules[higher_col] = pd.to_numeric(product_rules[higher_col], errors="coerce").fillna(0)
    product_rules[lower_col] = pd.to_numeric(product_rules[lower_col], errors="coerce").fillna(0)
    product_rules["多出条数"] = product_rules[higher_col] - product_rules[lower_col]
    product_rules = product_rules[product_rules["多出条数"] > 0].copy()
    if product_rules.empty:
        summary = {"新增品种数": 0, "新增总条数": 0, "新增总成本": 0.0, "新增总毛利": 0.0}
        return summary, pd.DataFrame(columns=["分组", "商品名称", "高档位上限", "低档位上限", "多出条数", "批发价", "行情价", "新增成本", "新增毛利"])

    merged = product_rules.merge(
        products_df[["商品", "批发价", "行情价"]].rename(columns={"商品": "商品名称"}),
        on="商品名称",
        how="left",
    )
    merged["行情价"] = pd.to_numeric(merged["行情价"], errors="coerce")
    merged["新增成本"] = merged["多出条数"] * merged["批发价"].fillna(0)
    effective_price = merged["行情价"].combine_first(merged["批发价"])
    merged["新增毛利"] = merged["多出条数"] * (effective_price.fillna(0) - merged["批发价"].fillna(0))

    result = merged.rename(
        columns={
            higher_col: "高档位上限",
            lower_col: "低档位上限",
        }
    )[["分组", "商品名称", "高档位上限", "低档位上限", "多出条数", "批发价", "行情价", "新增成本", "新增毛利"]]
    result = result.sort_values(["多出条数", "新增毛利", "新增成本"], ascending=[False, False, False], kind="stable")

    summary = {
        "新增品种数": int(len(result)),
        "新增总条数": int(result["多出条数"].sum()),
        "新增总成本": float(result["新增成本"].sum()),
        "新增总毛利": float(result["新增毛利"].sum()),
    }
    return summary, result


def normalize_period_rules(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    normalized = df.copy()
    normalized.columns = [str(col).strip() for col in normalized.columns]

    if "价位段" in normalized.columns:
        normalized["分组"] = normalized["价位段"].map(_normalize_band_name)
    elif "分组" in normalized.columns:
        normalized["分组"] = normalized["分组"].map(_normalize_band_name)

    if "商品名称" in normalized.columns:
        normalized["商品名称"] = normalized["商品名称"].astype(str).str.strip()

    if "商品编码" in normalized.columns:
        normalized["商品编码"] = normalized["商品编码"].map(_normalize_code)

    tier_columns = ["三十档", "二十九档", "二十八档", "二十七档", "二十六档"]
    for column in tier_columns:
        if column in normalized.columns:
            normalized[column] = normalized[column].map(_normalize_limit)

    if "商品名称" in normalized.columns:
        normalized["类型"] = "商品"
        normalized.loc[normalized["商品名称"] == "价位段总量上限", "类型"] = "分段上限"
        normalized.loc[normalized["商品名称"].isin(["可订货量合计", "投放量"]), "类型"] = "汇总"

    return normalized


def _normalize_band_name(value) -> str:
    text = str(value or "").strip().replace(" ", "")
    mapping = {
        "8-9段": "8-9段",
        "8-9 段": "8-9段",
        "8-9段": "8-9段",
        "8-9": "8-9段",
        "8-9段价位段总量上限": "8-9段",
        "10段": "10段",
        "11段": "11段",
        "12段": "12段",
        "13段": "13段",
        "14-15段": "14-15段",
        "按档位投放": "按档位投放",
    }
    cleaned = (
        text.replace("8-9段", "8-9段")
        .replace("8-9段", "8-9段")
        .replace("8-9", "8-9")
        .replace("1 0段", "10段")
        .replace("10段", "10段")
        .replace("1 1段", "11段")
        .replace("11段", "11段")
        .replace("1 2段", "12段")
        .replace("12段", "12段")
        .replace("13段", "13段")
        .replace("13段", "13段")
        .replace("14-15段", "14-15段")
    )
    cleaned = cleaned.replace("8-9段", "8-9段").replace("8-9", "8-9段")
    cleaned = cleaned.replace("10段", "10段").replace("11段", "11段").replace("12段", "12段")
    cleaned = cleaned.replace("13段", "13段").replace("14-15段", "14-15段")
    if cleaned in mapping:
        return mapping[cleaned]
    if "8-9" in cleaned:
        return "8-9段"
    if "10" in cleaned:
        return "10段"
    if "11" in cleaned:
        return "11段"
    if "12" in cleaned:
        return "12段"
    if "13" in cleaned:
        return "13段"
    if "14-15" in cleaned:
        return "14-15段"
    if "按档位投放" in cleaned:
        return "按档位投放"
    return text


def _normalize_limit(value):
    text = str(value or "").strip()
    if text in {"", "nan", "NaN"}:
        return pd.NA
    fixed = text.replace("]7", "7").replace("D", "0").replace("工", "1").replace("O", "0")
    digits = "".join(ch for ch in fixed if ch.isdigit() or ch == ".")
    if digits == "":
        return pd.NA
    try:
        number = float(digits)
    except ValueError:
        return pd.NA
    return int(number) if number.is_integer() else number


def _normalize_code(value):
    text = str(value or "").strip()
    if text in {"", "nan", "NaN"}:
        return pd.NA
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits if digits else pd.NA
