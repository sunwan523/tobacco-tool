from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    from pypinyin import Style, lazy_pinyin
except Exception:  # pragma: no cover - optional fallback
    Style = None
    lazy_pinyin = None


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "market_price_db.csv"
DB_COLUMNS = ["商品名称", "建议零售价", "批发价", "当期找货价格", "盒码", "条码"]


def load_price_db() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame(columns=DB_COLUMNS)
    data = pd.read_csv(DB_PATH, dtype={"盒码": "string", "条码": "string"})
    for column in DB_COLUMNS:
        if column not in data.columns:
            data[column] = pd.NA
    return data[DB_COLUMNS].copy()


def save_price_db(data: pd.DataFrame) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = data.copy()
    for column in DB_COLUMNS:
        if column not in data.columns:
            data[column] = pd.NA
    data[DB_COLUMNS].to_csv(DB_PATH, index=False, encoding="utf-8-sig")


def merge_uploaded_prices(existing: pd.DataFrame, uploaded: pd.DataFrame) -> pd.DataFrame:
    base = existing.copy()
    incoming = uploaded.copy()
    for column in DB_COLUMNS:
        if column not in base.columns:
            base[column] = pd.NA
        if column not in incoming.columns:
            incoming[column] = pd.NA
    merged = pd.concat([base[DB_COLUMNS], incoming[DB_COLUMNS]], ignore_index=True)
    merged["_key"] = merged.apply(build_key, axis=1)
    merged = merged.drop_duplicates(subset="_key", keep="last").drop(columns="_key")
    merged = merged.sort_values("商品名称").reset_index(drop=True)
    return merged


def upsert_manual_market_prices(existing: pd.DataFrame, manual: pd.DataFrame) -> pd.DataFrame:
    return merge_uploaded_prices(existing, manual)


def merge_order_products(existing: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    order_cols = [col for col in ["商品名称", "建议零售价", "批发价", "盒码", "条码"] if col in orders.columns]
    if not order_cols:
        return existing
    incoming = orders[order_cols].copy()
    incoming["当期找货价格"] = pd.NA

    base = existing.copy()
    for column in DB_COLUMNS:
        if column not in base.columns:
            base[column] = pd.NA
        if column not in incoming.columns:
            incoming[column] = pd.NA

    existing_keys = set(base.apply(build_key, axis=1).tolist()) if not base.empty else set()
    incoming["_key"] = incoming.apply(build_key, axis=1)
    incoming = incoming[~incoming["_key"].isin(existing_keys)].drop(columns="_key")
    if incoming.empty:
        return base[DB_COLUMNS].copy()
    merged = pd.concat([base[DB_COLUMNS], incoming[DB_COLUMNS]], ignore_index=True)
    return merged.sort_values("商品名称").reset_index(drop=True)


def search_prices(data: pd.DataFrame, query: str) -> pd.DataFrame:
    text = (query or "").strip().lower()
    if not text:
        return data.sort_values("商品名称").reset_index(drop=True)

    indexed = data.copy()
    indexed["名称小写"] = indexed["商品名称"].fillna("").astype(str).str.lower()
    indexed["拼音首字母"] = indexed["商品名称"].fillna("").astype(str).map(to_initials)
    indexed["拼音全拼"] = indexed["商品名称"].fillna("").astype(str).map(to_pinyin)
    indexed["条码文本"] = indexed["条码"].fillna("").astype(str)
    indexed["盒码文本"] = indexed["盒码"].fillna("").astype(str)

    mask = indexed["名称小写"].str.contains(text, na=False)
    mask |= indexed["拼音首字母"].str.contains(text, na=False)
    mask |= indexed["拼音全拼"].str.contains(text, na=False)
    mask |= indexed["条码文本"].eq(text)
    mask |= indexed["盒码文本"].eq(text)
    if len(text) >= 4:
        mask |= indexed["条码文本"].str.contains(text, na=False)
        mask |= indexed["盒码文本"].str.contains(text, na=False)
    return indexed.loc[mask, DB_COLUMNS].sort_values("商品名称").reset_index(drop=True)


def build_key(row: pd.Series) -> str:
    barcode = normalize_code(row.get("条码"))
    if barcode:
        return f"barcode:{barcode}"
    boxcode = normalize_code(row.get("盒码"))
    if boxcode:
        return f"box:{boxcode}"
    return f"name:{str(row.get('商品名称', '')).strip()}"


def normalize_code(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).replace(".0", "").strip()


def to_initials(text: str) -> str:
    if not text:
        return ""
    if lazy_pinyin is None or Style is None:
        return text.lower()
    return "".join(lazy_pinyin(text, style=Style.FIRST_LETTER)).lower()


def to_pinyin(text: str) -> str:
    if not text:
        return ""
    if lazy_pinyin is None:
        return text.lower()
    return "".join(lazy_pinyin(text)).lower()
