"""投放表自动分析与同步归档（tobacco-tool 侧）。

职责：
1. 扫描「历史投入表」目录（含季度子目录），找出本地档案库中尚未分析过的周投放表；
2. 用 parse_strategy 分析并入库（本地 SQLite allocation_archive.db，按 week_label 可查）；
3. 与库存系统（mhtc-juanyankucun）的周次列表比对：已存在的周不重复推送，缺失的周才推送；
4. 把“已同步 / 待同步”状态记录回本地库，供界面与下次同步使用。

所有内容都存核心投放结果：各价位段/档位投放明细(strategy_items)、段位上限(segment_limits)、
官方“可订货量合计”(tier_totals)，即推送给库存系统的那份数据。
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd

from tobacco_core.analysis import parse_strategy
from tobacco_core.push_client import build_payload, extract_week_label, fetch_kucun_weeks, push_allocation

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALLOCATION_DIR = PROJECT_ROOT / "历史投入表"
DATA_DIR = PROJECT_ROOT / "data"
ARCHIVE_DB_PATH = DATA_DIR / "allocation_archive.db"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ARCHIVE_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS weeks (
            week_label    TEXT PRIMARY KEY,
            source_file   TEXT,
            file_mtime    TEXT,
            analyzed_at   TEXT,
            items_json    TEXT,
            limits_json   TEXT,
            totals_json   TEXT,
            kucun_status  TEXT,
            push_message  TEXT,
            pushed_at     TEXT
        )
        """
    )
    conn.commit()
    return conn


def _sanitize_records(records: list[dict]) -> list[dict]:
    """把 numpy 浮点 NaN 等转成 JSON 可序列化形式。"""
    cleaned: list[dict] = []
    for rec in records:
        row: dict = {}
        for key, value in rec.items():
            if isinstance(value, float) and math.isnan(value):
                row[key] = None
            elif isinstance(value, (int, float, str)) or value is None:
                row[key] = value
            else:
                row[key] = None
        cleaned.append(row)
    return cleaned


def _df_to_json(df: pd.DataFrame) -> str:
    records = _sanitize_records(df.to_dict(orient="records"))
    return json.dumps(records, ensure_ascii=False)


def _df_from_json(text: str | None) -> pd.DataFrame:
    if not text:
        return pd.DataFrame()
    try:
        return pd.DataFrame(json.loads(text))
    except Exception:
        return pd.DataFrame()


# ---------------------- 档案库读写 ----------------------

def archived_week_labels() -> set[str]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT week_label FROM weeks").fetchall()
        return {str(row["week_label"]) for row in rows}
    finally:
        conn.close()


def list_weeks() -> list[dict]:
    """按投放表文件时间倒序返回已归档周（供界面下拉/列表用）。"""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT week_label, source_file, file_mtime, analyzed_at, kucun_status,
                   pushed_at, push_message, totals_json
            FROM weeks ORDER BY file_mtime DESC, week_label DESC
            """
        ).fetchall()
        result = []
        for row in rows:
            totals = _df_from_json(row["totals_json"])
            official_total = 0
            if not totals.empty and "可订货量合计" in totals.columns:
                official_total = int(pd.to_numeric(totals["可订货量合计"], errors="coerce").fillna(0).sum())
            result.append(
                {
                    "week_label": row["week_label"],
                    "source_file": row["source_file"],
                    "file_mtime": row["file_mtime"],
                    "analyzed_at": row["analyzed_at"],
                    "kucun_status": row["kucun_status"],
                    "pushed_at": row["pushed_at"],
                    "push_message": row["push_message"],
                    "official_total": official_total,
                }
            )
        return result
    finally:
        conn.close()


def load_week(week_label: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM weeks WHERE week_label = ?", (week_label,)).fetchone()
        if not row:
            return None
        return {
            "week_label": row["week_label"],
            "source_file": row["source_file"],
            "file_mtime": row["file_mtime"],
            "analyzed_at": row["analyzed_at"],
            "kucun_status": row["kucun_status"],
            "pushed_at": row["pushed_at"],
            "push_message": row["push_message"],
            "strategy_items": _df_from_json(row["items_json"]),
            "segment_limits": _df_from_json(row["limits_json"]),
            "tier_totals": _df_from_json(row["totals_json"]),
        }
    finally:
        conn.close()


def _archive_week(
    conn: sqlite3.Connection,
    week_label: str,
    source_file: str,
    file_mtime_iso: str,
    strategy_items: pd.DataFrame,
    segment_limits: pd.DataFrame,
    tier_totals: pd.DataFrame,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT OR REPLACE INTO weeks
        (week_label, source_file, file_mtime, analyzed_at, items_json, limits_json, totals_json, kucun_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            week_label,
            source_file,
            file_mtime_iso,
            now,
            _df_to_json(strategy_items),
            _df_to_json(segment_limits),
            _df_to_json(tier_totals),
        ),
    )


def _mark_week_status(conn: sqlite3.Connection, week_label: str, status: str, message: str, pushed: bool = False) -> None:
    if pushed:
        conn.execute(
            "UPDATE weeks SET kucun_status = ?, push_message = ?, pushed_at = ? WHERE week_label = ?",
            (status, message, datetime.now().isoformat(timespec="seconds"), week_label),
        )
    else:
        conn.execute(
            "UPDATE weeks SET kucun_status = ?, push_message = ? WHERE week_label = ?",
            (status, message, week_label),
        )


def _find_allocation_files() -> list[Path]:
    if not ALLOCATION_DIR.exists():
        return []
    return sorted(
        (p for p in ALLOCATION_DIR.rglob("*.xlsx") if not p.name.startswith("~$")),
        key=lambda p: os.path.getmtime(p),
    )


def path_for_week(week_label: str) -> Path | None:
    for p in _find_allocation_files():
        if extract_week_label(p.name) == week_label:
            return p
    return None


# ---------------------- 同步主流程 ----------------------

def run_sync() -> dict:
    """扫描新投放表 → 分析归档 → 与库存系统比对 → 只推缺失周。

    返回汇总信息，供页面展示。
    """
    summary: dict = {
        "scanned": 0,
        "archived": [],
        "skipped_existing": 0,
        "pushed": [],
        "already_in_kucun": [],
        "pending": [],
        "errors": [],
        "kucun_ok": True,
        "newest_processed": None,
        "newest_mtime": 0.0,
    }
    files = _find_allocation_files()
    summary["scanned"] = len(files)
    existing = archived_week_labels()
    conn = _connect()
    try:
        for path in files:
            week_label = extract_week_label(path.name)
            if not week_label:
                summary["errors"].append(f"{path.name}: 文件名无法识别周标识")
                continue
            if week_label in existing:
                summary["skipped_existing"] += 1
                continue
            try:
                mtime_iso = datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")
                data = path.read_bytes()
                stream = BytesIO(data)
                stream.name = path.name
                strategy_items, segment_limits, tier_totals = parse_strategy(stream)
                if strategy_items.empty:
                    raise ValueError("分析结果为空（未找到有效投放行）")
                _archive_week(conn, week_label, str(path), mtime_iso, strategy_items, segment_limits, tier_totals)
                existing.add(week_label)
                summary["archived"].append(week_label)
                mtime = os.path.getmtime(path)
                if mtime > summary["newest_mtime"]:
                    summary["newest_mtime"] = mtime
                    summary["newest_processed"] = week_label
            except Exception as exc:  # noqa: BLE001 - 单文件解析失败不影响其它周
                summary["errors"].append(f"{week_label}: {exc}")

        # 与库存系统比对：只推缺失周；已存在的只做标记，不重复推送
        kucun_weeks = fetch_kucun_weeks()
        if kucun_weeks is None:
            summary["kucun_ok"] = False
            kucun_set: set[str] | None = None
        else:
            kucun_set = set(kucun_weeks)

        if kucun_set is None:
            candidates = conn.execute(
                "SELECT week_label FROM weeks WHERE kucun_status IS NULL OR kucun_status = 'pending'"
            ).fetchall()
            for row in candidates:
                _mark_week_status(conn, row["week_label"], "pending", "库存系统未连接，待下次同步")
                summary["pending"].append(row["week_label"])
        else:
            candidates = conn.execute(
                "SELECT week_label FROM weeks WHERE kucun_status IS NULL OR kucun_status = 'pending'"
            ).fetchall()
            for row in candidates:
                label = row["week_label"]
                if label in kucun_set:
                    _mark_week_status(conn, label, "present", "库存系统已存在该周，未重复推送")
                    summary["already_in_kucun"].append(label)
                    continue
                week = load_week(label)
                if not week:
                    continue
                payload = build_payload(
                    week["strategy_items"],
                    week["segment_limits"],
                    label,
                    week["tier_totals"],
                    week["file_mtime"],
                )
                ok, message = push_allocation(payload)
                if ok:
                    _mark_week_status(conn, label, "pushed", message, pushed=True)
                    summary["pushed"].append(label)
                else:
                    _mark_week_status(conn, label, "pending", message)
                    summary["pending"].append(f"{label}（{message}）")
        conn.commit()
    finally:
        conn.close()
    return summary
