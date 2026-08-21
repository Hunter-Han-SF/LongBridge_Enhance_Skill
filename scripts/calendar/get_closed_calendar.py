"""获取市场休市日历(节假日)。

对应 Longbridge CLI: finance-calendar closed --market
列出各交易所即将到来的休市日(全日/半日),做交易日历规划用。

用法:
    python get_closed_calendar.py                          # 全市场
    python get_closed_calendar.py --market US
    python get_closed_calendar.py --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_finance_calendar,
    is_empty,
    print_display_table,
    print_error,
    print_json,
)


def _flatten_closed(buckets: list[dict]) -> list[dict]:
    events = []
    for b in buckets:
        for info in b.get("infos", []):
            if not isinstance(info, dict):
                continue
            ext = info.get("ext") or {}
            events.append({
                "holiday": info.get("content", ""),
                "date": ext.get("holiday_date") or b.get("date", ""),
                "type": ext.get("holiday_type") or info.get("date_type", ""),
                "date_type": info.get("date_type", ""),
            })
    return events


def fetch_closed_calendar(
    market: str | None = None,
    count: int = 50,
    output_json: bool = False,
) -> dict:
    buckets = get_finance_calendar(category="closed", market=market, count=count)
    if is_empty(buckets):
        raise ValueError(f"无休市日历数据({market or '全市场'})。")

    events = _flatten_closed(buckets)
    result = {
        "market": market or "ALL",
        "date_range": f"{buckets[0]['date']} ~ {buckets[-1]['date']}",
        "total_events": len(events),
        "events": events,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{market or '全市场'} 休市日历({len(events)} 个假日)")
    print(f"  日期范围: {result['date_range']}")
    print()
    rows = [{
        "假日": e["holiday"],
        "日期": e["date"],
        "类型": {"full_day": "全日休市", "half_day": "半日市"}.get(
            e["type"], e["type"] or e["date_type"]),
    } for e in events]
    print_display_table(rows, columns=["假日", "日期", "类型"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="市场休市日历(节假日)")
    parser.add_argument("--market", default=None, help="HK|US|CN|SG|...(留空=全市场)")
    parser.add_argument("--count", type=int, default=50, help="返回事件数上限(默认 50)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_closed_calendar(market=args.market, count=args.count,
                              output_json=args.output_json)
    except Exception as e:
        print_error("获取休市日历", str(e))
        sys.exit(1)
