"""把投放表解析结果推送到卷烟库存项目（mhtc-juanyankucun）。

服务端接口：POST http://localhost:30000/api/allocation/push
鉴权方式：请求头 X-Site-Password
幂等策略：同一 week_label 重复推送会覆盖服务端已有数据
"""

from __future__ import annotations

import math
import time

import requests

PUSH_URL = "http://localhost:30000/api/allocation/push"
BATCHES_URL = "http://localhost:30000/api/allocation/batches"
SITE_PASSWORD = "523626"

# 库存系统周次列表的进程内缓存（避免界面每次重算都重复请求）
_kucun_weeks_cache: dict = {}


def _clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _clean_int(value) -> int | None:
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def extract_week_label(file_name: str | None) -> str | None:
    """从投放表文件名提取周标识：'2026年9月第2周 .xlsx' -> '2026年9月第2周'。

    无法匹配“YYYY年M月第N周”时回退为文件名去扩展名，保证仍可推送。
    """
    if not file_name:
        return None
    stem = str(file_name).rsplit(".", 1)[0].strip()
    return stem or None


def build_payload(strategy_items, segment_limits, week_label: str, tier_totals=None, file_mtime=None) -> dict:
    """把 parse_strategy 的结果转换为服务端推送格式。

    items: 每行商品，tiers 为 {"档位rank": 数量}（rank 1~30，三十档=30）
    limits: 每行段位上限，同 tiers 结构
    totals: 各档位官方"可订货量合计"（含二次自选等待选量，口径为实际可订上限）
    file_mtime: 投放表文件的最后修改时间（ISO字符串或None），
                服务端用它推导投放周起始日（文件保存于投放前两三天，投放周从其后第一个周一开始）
    """
    from tobacco_core.analysis import TIER_COLUMNS

    tier_ranks = {name: len(TIER_COLUMNS) - idx for idx, name in enumerate(TIER_COLUMNS)}

    def collect_tiers(row: dict) -> dict:
        tiers: dict[str, int] = {}
        for tier_name, qty in row.items():
            rank = tier_ranks.get(tier_name)
            if rank is None:
                continue
            q = _clean_int(qty)
            if q is not None and q > 0:
                tiers[str(rank)] = q
        return tiers

    items = []
    for row in strategy_items.to_dict("records"):
        items.append(
            {
                "segment": _clean_text(row.get("价位段")),
                "product_code": _clean_text(row.get("商品编码")),
                "product_name": _clean_text(row.get("商品名称")),
                "tiers": collect_tiers(row),
            }
        )

    limits = []
    for row in segment_limits.to_dict("records"):
        limits.append({"segment": _clean_text(row.get("价位段")), "tiers": collect_tiers(row)})

    totals: dict[str, int] = {}
    if tier_totals is not None and not tier_totals.empty:
        for row in tier_totals.to_dict("records"):
            rank = tier_ranks.get(_clean_text(row.get("档位")))
            q = _clean_int(row.get("可订货量合计"))
            if rank is not None and q is not None and q > 0:
                totals[str(rank)] = q

    return {"week_label": week_label, "items": items, "limits": limits, "totals": totals, "file_mtime": file_mtime}


def push_allocation(payload: dict, timeout: float = 20.0) -> tuple[bool, str]:
    try:
        resp = requests.post(
            PUSH_URL,
            json=payload,
            headers={"X-Site-Password": SITE_PASSWORD},
            timeout=timeout,
        )
        data = resp.json()
        if resp.ok and data.get("success"):
            # 推送成功即更新进程内周次缓存，避免短期内重复判断导致再次推送
            cached_weeks = _kucun_weeks_cache.get("weeks")
            if isinstance(cached_weeks, list):
                label = payload.get("week_label")
                if label and label not in cached_weeks:
                    cached_weeks.append(label)
                _kucun_weeks_cache["ts"] = time.time()
            return True, f"已同步到库存系统（{data.get('saved_items', 0)} 条档位明细）"
        return False, f"同步失败：{data.get('message') or resp.status_code}"
    except Exception as exc:
        return False, f"同步失败：{exc}"


def fetch_kucun_weeks(ttl: float = 60.0) -> list[str] | None:
    """拉取库存系统已推送的周次列表（接口开放，无需鉴权）。

    返回 None 表示库存系统不可达/查询失败（与“空列表”区分）。
    进程内带 TTL 缓存，避免频繁请求。
    """
    now = time.time()
    cached = _kucun_weeks_cache.get("weeks")
    cached_at = _kucun_weeks_cache.get("ts", 0)
    if cached is not None and now - cached_at < ttl:
        return cached
    try:
        resp = requests.get(BATCHES_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else data
        weeks = [str(item.get("week_label")) for item in rows if isinstance(item, dict) and item.get("week_label")]
        _kucun_weeks_cache["weeks"] = weeks
        _kucun_weeks_cache["ts"] = now
        return weeks
    except Exception:
        return None


def kucun_has_week(week_label: str, ttl: float = 60.0) -> bool | None:
    """week_label 是否已在库存系统。None = 无法确认（库存系统不可达）。"""
    weeks = fetch_kucun_weeks(ttl)
    if weeks is None:
        return None
    return week_label in weeks
