from __future__ import annotations

from io import BytesIO
from typing import Iterable

import pandas as pd


def read_excel_like(file_obj) -> pd.DataFrame:
    raw = file_obj.read()
    if not raw:
        return pd.DataFrame()

    name = getattr(file_obj, "name", "").lower()
    if name.endswith(".csv"):
        return pd.read_csv(BytesIO(raw))

    return pd.read_excel(BytesIO(raw), header=None)


def normalize_dataframe(raw_df: pd.DataFrame, required_keywords: Iterable[str]) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame()

    header_index = find_header_row(raw_df, required_keywords)
    if header_index is None:
        return pd.DataFrame()

    header = [str(value).strip() for value in raw_df.iloc[header_index].tolist()]
    body = raw_df.iloc[header_index + 1 :].copy()
    body.columns = header
    body = body.reset_index(drop=True)
    return body


def find_header_row(raw_df: pd.DataFrame, required_keywords: Iterable[str]) -> int | None:
    keywords = list(required_keywords)
    for idx in range(len(raw_df)):
        row_text = " | ".join(str(value) for value in raw_df.iloc[idx].tolist())
        if all(keyword in row_text for keyword in keywords):
            return idx
    return None


def find_column(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    cols = [str(col).strip() for col in columns]
    for candidate in candidates:
        for col in cols:
            if candidate in col:
                return col
    return None


def to_number(value) -> float | None:
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
