from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    from pypinyin import Style, lazy_pinyin, pinyin
except Exception:  # pragma: no cover - optional fallback
    Style = None
    lazy_pinyin = None
    pinyin = None

import re


def remove_symbols(text: str) -> str:
    """去除文本中的符号，只保留中文、英文、数字"""
    if not text:
        return ""
    # 保留中文、英文、数字
    return re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text)


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
    
    base["当期找货价格"] = pd.NA
    
    base["_key"] = base.apply(build_key, axis=1)
    incoming["_key"] = incoming.apply(build_key, axis=1)
    
    for _, row in incoming.iterrows():
        key = row["_key"]
        market_price = row["当期找货价格"]
        
        mask = base["_key"] == key
        if mask.any():
            base.loc[mask, "当期找货价格"] = market_price
        else:
            product_name = str(row.get("商品名称", "")).strip()
            if product_name:
                name_mask = base["商品名称"].str.strip() == product_name
                if name_mask.any():
                    base.loc[name_mask, "当期找货价格"] = market_price
                else:
                    base = pd.concat([base, incoming.loc[[_]]], ignore_index=True)
            else:
                base = pd.concat([base, incoming.loc[[_]]], ignore_index=True)
    
    base = base.drop(columns="_key")
    base = base.sort_values("商品名称").reset_index(drop=True)
    return base


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
    original_text = (query or "").strip()
    text = original_text.lower()
    if not text:
        return data.sort_values("商品名称").reset_index(drop=True)

    # 去除搜索文本中的符号
    text_no_symbols = remove_symbols(text)

    indexed = data.copy()
    # 商品名称处理：去除符号并转小写
    indexed["名称处理"] = indexed["商品名称"].fillna("").astype(str).apply(remove_symbols).str.lower()
    indexed["名称原始小写"] = indexed["商品名称"].fillna("").astype(str).str.lower()
    indexed["拼音首字母"] = indexed["商品名称"].fillna("").astype(str).map(to_initials)
    indexed["拼音全拼"] = indexed["商品名称"].fillna("").astype(str).map(to_pinyin)
    indexed["条码文本"] = indexed["条码"].fillna("").astype(str)
    indexed["盒码文本"] = indexed["盒码"].fillna("").astype(str)

    # 匹配逻辑
    mask = indexed["名称原始小写"].str.contains(text, na=False)
    mask |= indexed["名称处理"].str.contains(text_no_symbols, na=False)
    
    # 拼音首字母匹配：支持单个首字母或多个首字母组合匹配
    # 对于多音字，每个字有多个可能的首字母，用空格分隔
    # 我们需要检查搜索文本是否能匹配任意一种可能的组合
    def match_pinyin_initials(pinyin_str, search_str):
        if not pinyin_str or not search_str:
            return False
        
        # 拆分带空格和不带空格的版本
        if "|" in pinyin_str:
            spaced_part, unspaced_part = pinyin_str.split("|", 1)
        else:
            spaced_part = pinyin_str
            unspaced_part = pinyin_str.replace(" ", "")
        
        # 首先尝试不带空格的匹配（支持连续搜索如xmyjd）
        if search_str in unspaced_part:
            return True
        
        # 然后尝试带空格的多音字匹配
        if " " in spaced_part:
            # 拆分每个字的可能首字母
            char_options = spaced_part.split(" ")
            # 对于搜索字符串的每个位置，检查是否能匹配该位置字的任意一个首字母
            if len(search_str) > len(char_options):
                return False
            # 检查是否是完全匹配（从开头开始）
            for i in range(len(search_str)):
                if i >= len(char_options):
                    return False
                # 检查搜索字符是否在该位置的可能首字母中
                if search_str[i] not in char_options[i]:
                    return False
            return True
        
        # 最后尝试直接匹配
        return search_str in spaced_part
    
    # 应用拼音首字母匹配
    pinyin_mask = indexed["拼音首字母"].apply(lambda x: match_pinyin_initials(x, text_no_symbols))
    mask |= pinyin_mask
    
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
        return remove_symbols(text).lower()
    
    # 先去除符号
    clean_text = remove_symbols(text)
    
    # 使用 pinyin 获取多音字的所有可能读音
    if pinyin is not None:
        try:
            # 获取所有可能的拼音组合（只获取首字母）
            pinyin_list = pinyin(clean_text, style=Style.FIRST_LETTER, heteronym=True)
            # 对于每个字，取所有可能的首字母，用空格分隔
            initials = []
            for char_pinyins in pinyin_list:
                # 去重并排序
                unique_pinyins = sorted(set(char_pinyins))
                initials.append("".join(unique_pinyins).lower())
            # 同时返回带空格和不带空格的版本，用|分隔
            spaced = " ".join(initials)
            unspaced = "".join(initials)
            return f"{spaced}|{unspaced}"
        except:
            pass
    
    # 如果多音字处理失败，回退到原来的方法
    simple = "".join(lazy_pinyin(clean_text, style=Style.FIRST_LETTER)).lower()
    return f"{simple}|{simple}"


def to_pinyin(text: str) -> str:
    if not text:
        return ""
    if lazy_pinyin is None:
        return remove_symbols(text).lower()
    return "".join(lazy_pinyin(text)).lower()
