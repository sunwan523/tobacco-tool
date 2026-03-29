from __future__ import annotations

from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PRICE_DB_PATH = DATA_DIR / "price_catalog.csv"
MARKET_PRICE_HISTORY_PATH = DATA_DIR / "market_price_history.csv"
HISTORY_ORDERS_PATH = DATA_DIR / "history_orders.csv"

PRICE_COLUMNS = ["商品", "指导零售价", "批发价", "行情价"]
MARKET_PRICE_COLUMNS = ["商品", "行情价", "生效日期", "来源文件"]
HISTORY_COLUMNS = ["商品", "指导零售价", "批发价", "订单量", "金额", "订单日期", "订单编号", "来源文件"]


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_price_catalog() -> pd.DataFrame:
    ensure_data_dir()
    if not PRICE_DB_PATH.exists():
        return pd.DataFrame(columns=PRICE_COLUMNS)
    df = pd.read_csv(PRICE_DB_PATH, encoding="utf-8-sig")
    for column in PRICE_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df[PRICE_COLUMNS].copy()


def save_price_catalog(df: pd.DataFrame) -> None:
    ensure_data_dir()
    catalog = df.copy()
    for column in PRICE_COLUMNS:
        if column not in catalog.columns:
            catalog[column] = pd.NA
    catalog = catalog[PRICE_COLUMNS].copy()
    catalog["商品"] = catalog["商品"].astype(str).str.strip()
    catalog = catalog[catalog["商品"].ne("") & catalog["商品"].ne("nan")]
    catalog = catalog.groupby("商品", as_index=False).last().sort_values("商品", kind="stable")
    catalog.to_csv(PRICE_DB_PATH, index=False, encoding="utf-8-sig")


def load_market_price_history() -> pd.DataFrame:
    ensure_data_dir()
    if not MARKET_PRICE_HISTORY_PATH.exists():
        return pd.DataFrame(columns=MARKET_PRICE_COLUMNS)
    df = pd.read_csv(MARKET_PRICE_HISTORY_PATH, encoding="utf-8-sig")
    for column in MARKET_PRICE_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df["生效日期"] = pd.to_datetime(df["生效日期"], errors="coerce").dt.date
    df["行情价"] = pd.to_numeric(df["行情价"], errors="coerce")
    return df[MARKET_PRICE_COLUMNS].copy()


def append_market_price_history(df: pd.DataFrame) -> pd.DataFrame:
    ensure_data_dir()
    existing = load_market_price_history()
    incoming = df.copy()
    for column in MARKET_PRICE_COLUMNS:
        if column not in incoming.columns:
            incoming[column] = pd.NA
    incoming = incoming[MARKET_PRICE_COLUMNS].copy()
    incoming["商品"] = incoming["商品"].astype(str).str.strip()
    incoming["行情价"] = pd.to_numeric(incoming["行情价"], errors="coerce")
    incoming["生效日期"] = pd.to_datetime(incoming["生效日期"], errors="coerce").dt.date
    incoming = incoming[incoming["商品"].ne("") & incoming["商品"].ne("nan")]
    incoming = incoming.dropna(subset=["商品", "行情价", "生效日期"])

    merged = pd.concat([existing, incoming], ignore_index=True)
    merged = merged.drop_duplicates(subset=["商品", "生效日期"], keep="last")
    merged = merged.sort_values(["生效日期", "商品"], kind="stable")
    merged.to_csv(MARKET_PRICE_HISTORY_PATH, index=False, encoding="utf-8-sig")
    return load_market_price_history()


def load_history_orders() -> pd.DataFrame:
    ensure_data_dir()
    if not HISTORY_ORDERS_PATH.exists():
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    df = pd.read_csv(HISTORY_ORDERS_PATH, encoding="utf-8-sig")
    for column in HISTORY_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df["订单日期"] = pd.to_datetime(df["订单日期"], errors="coerce").dt.date
    for column in ["指导零售价", "批发价", "订单量", "金额"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df[HISTORY_COLUMNS].copy()


def append_history_orders(df: pd.DataFrame) -> pd.DataFrame:
    ensure_data_dir()
    existing = load_history_orders()
    incoming = df.copy()
    for column in HISTORY_COLUMNS:
        if column not in incoming.columns:
            incoming[column] = pd.NA
    incoming = incoming[HISTORY_COLUMNS].copy()
    incoming["订单日期"] = pd.to_datetime(incoming["订单日期"], errors="coerce").dt.date
    for column in ["指导零售价", "批发价", "订单量", "金额"]:
        incoming[column] = pd.to_numeric(incoming[column], errors="coerce")

    merged = pd.concat([existing, incoming], ignore_index=True)
    if merged.empty:
        merged.to_csv(HISTORY_ORDERS_PATH, index=False, encoding="utf-8-sig")
        return merged

    merged["订单金额明细"] = merged["金额"]
    fallback_amount = merged["订单量"].fillna(0) * merged["批发价"].fillna(0)
    merged["订单金额明细"] = merged["订单金额明细"].fillna(fallback_amount)
    order_level = (
        merged.groupby(["订单日期", "订单编号", "来源文件"], dropna=False, as_index=False)
        .agg(订单总金额=("订单金额明细", "sum"))
        .sort_values(["订单日期", "订单编号", "来源文件"], kind="stable")
    )
    order_level["订单去重键"] = order_level["订单日期"].astype(str).fillna("") + "|" + order_level["订单总金额"].round(2).astype(str)
    order_level = order_level.drop_duplicates(subset=["订单去重键"], keep="first")
    merged = merged.merge(order_level[["订单日期", "订单编号", "来源文件"]], on=["订单日期", "订单编号", "来源文件"], how="inner")
    merged = merged.drop(columns=["订单金额明细"])
    merged = merged.sort_values(["订单日期", "订单编号", "来源文件", "商品"], kind="stable")
    merged.to_csv(HISTORY_ORDERS_PATH, index=False, encoding="utf-8-sig")
    return load_history_orders()
