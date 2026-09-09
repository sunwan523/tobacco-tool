"""一次性导入 历史投入表/ 下所有周投放表到卷烟库存系统。

用法：
    .venv\\Scripts\\python.exe push_history.py

前提：库存系统服务已启动（http://localhost:30000）。
同一周重复运行会覆盖服务端数据，可安全反复执行。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path

from tobacco_core.analysis import parse_strategy
from tobacco_core.push_client import build_payload, extract_week_label, push_allocation

BASE_DIR = Path(__file__).resolve().parent / "历史投入表"


def main() -> int:
    files = sorted(f for f in BASE_DIR.rglob("*.xlsx") if not f.name.startswith("~$"))
    if not files:
        print(f"未在 {BASE_DIR} 找到投放表文件")
        return 1
    print(f"共找到 {len(files)} 个投放表文件\n")
    ok_count = 0
    for f in files:
        week_label = extract_week_label(f.name)
        if not week_label:
            print(f"[跳过] 无法识别周标识：{f.name}")
            continue
        try:
            with f.open("rb") as fh:
                data = fh.read()
            strategy_items, segment_limits, tier_totals = parse_strategy(BytesIO(data))
        except Exception as exc:
            print(f"[失败] {week_label}：解析失败 {exc}")
            continue
        mtime_iso = datetime.fromtimestamp(os.path.getmtime(f)).isoformat()
        payload = build_payload(strategy_items, segment_limits, week_label, tier_totals, mtime_iso)
        ok, message = push_allocation(payload)
        mark = "成功" if ok else "失败"
        print(f"[{mark}] {week_label}：商品 {len(payload['items'])} 行，{message}")
        if ok:
            ok_count += 1
    print(f"\n完成：成功 {ok_count}/{len(files)}")
    return 0 if ok_count == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
