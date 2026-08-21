"""获取 IPO 上市日历。

对应 Longbridge CLI: finance-calendar ipo --market --start --end
按日期分桶列出即将/近期上市的新股事件。

用法:
    python get_ipo_calendar.py                          # 全市场近期
    python get_ipo_calendar.py --market US
    python get_ipo_calendar.py --market HK --count 30
    python get_ipo_calendar.py --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    counter_id_to_symbol,
    get_finance_calendar,
    is_empty,
    print_display_table,
    print_error,
    print_json,
)


def _flatten_ipos(buckets: list[dict]) -> list[dict]:
    events = []
    for b in buckets:
        for info in b.get("infos", []):
            if not isinstance(info, dict):
                continue
            ext = info.get("ext") or {}
            events.append({
                "symbol": counter_id_to_symbol(info.get("counter_id", "")) or info.get("counter_id", ""),
                "name": info.get("counter_name", ""),
                "date": info.get("date", ""),
                "content": info.get("content", ""),
                "industry": ext.get("industry", ""),
            })
    return events


def fetch_ipo_calendar(
    market: str | None = None,
    start: str | None = None,
    end: str | None = None,
    count: int = 50,
    output_json: bool = False,
) -> dict:
    buckets = get_finance_calendar(category="ipo", market=market,
                                   start=start, end=end, count=count)
    if is_empty(buckets):
        raise ValueError(f"近期无 IPO 事件({market or '全市场'})。"
                         "也可用 get_ipo_listings.py 看认购/暗盘/已上市阶段明细。")

    events = _flatten_ipos(buckets)
    result = {
        "market": market or "ALL",
        "date_range": f"{buckets[0]['date']} ~ {buckets[-1]['date']}",
        "total_events": len(events),
        "events": events,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{market or '全市场'} IPO 上市日历({len(events)} 个事件)")
    print(f"  日期范围: {result['date_range']}")
    print()
    rows = [{
        "symbol": e["symbol"],
        "name": e["name"][:14],
        "上市日": e["date"],
        "行业": e["industry"][:12],
        "内容": e["content"][:24],
    } for e in events]
    print_display_table(rows, columns=["symbol", "name", "上市日", "行业", "内容"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IPO 上市日历")
    parser.add_argument("--market", default=None, help="HK|US|CN|SG|...(留空=全市场)")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--count", type=int, default=50, help="返回事件数上限(默认 50)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_ipo_calendar(market=args.market, start=args.start, end=args.end,
                           count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取 IPO 日历", str(e))
        sys.exit(1)
