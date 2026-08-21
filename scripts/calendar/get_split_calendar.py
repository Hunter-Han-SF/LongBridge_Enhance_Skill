"""获取拆股/合股日历。

对应 Longbridge CLI: finance-calendar split --market --symbol --start --end
官方 skill 无此加工分析。事件含拆股比例(从 content 解析,如"5 股合并为 1 股")。

用法:
    python get_split_calendar.py                          # 全市场近期
    python get_split_calendar.py --market US
    python get_split_calendar.py --market US --count 30
    python get_split_calendar.py --symbol AAPL.US
    python get_split_calendar.py --json
"""
from __future__ import annotations

import argparse
import os
import re
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


def parse_split_ratio(content: str) -> str:
    """从 '5 股合并为 1 股' / '1 股拆分为 4 股' 解析比例。"""
    m = re.search(r"(\d[\d.]*)\s*股\s*(合并为|拆分为|拆折为)\s*(\d[\d.]*)\s*股", str(content))
    if not m:
        return ""
    x, action, y = m.group(1), m.group(2), m.group(3)
    kind = "合股" if "合并" in action else "拆股"
    return f"{x}→{y}({kind})"


def _flatten_splits(buckets: list[dict]) -> list[dict]:
    events = []
    for b in buckets:
        for info in b.get("infos", []):
            if not isinstance(info, dict):
                continue
            ext = info.get("ext") or {}
            content = info.get("content", "")
            events.append({
                "symbol": counter_id_to_symbol(info.get("counter_id", "")) or info.get("counter_id", ""),
                "name": info.get("counter_name", ""),
                "date": info.get("date", ""),
                "ratio": parse_split_ratio(content),
                "content": content,
                "announcement_date": ext.get("announcement_date", ""),
                "industry": ext.get("industry", ""),
            })
    return events


def fetch_split_calendar(
    market: str | None = None,
    symbol: str | None = None,
    watchlist: bool = False,
    start: str | None = None,
    end: str | None = None,
    count: int = 50,
    output_json: bool = False,
) -> dict:
    filter_arg = "watchlist" if watchlist and not symbol else None
    buckets = get_finance_calendar(
        category="split", market=market, symbol=symbol, filter=filter_arg,
        start=start, end=end, count=count,
    )
    if is_empty(buckets):
        scope = symbol or (f"{market or '全市场'}" + (" 自选股" if watchlist else ""))
        raise ValueError(f"近期无拆股/合股事件({scope})。")

    events = _flatten_splits(buckets)
    result = {
        "market": market or "ALL",
        "symbol": symbol,
        "date_range": f"{buckets[0]['date']} ~ {buckets[-1]['date']}",
        "total_events": len(events),
        "events": events,
    }

    if output_json:
        print_json(result)
        return result

    scope = symbol or (f"{market or '全市场'}" + (" 自选股" if watchlist else ""))
    print(f"{scope} 拆股/合股日历({len(events)} 个事件)")
    print(f"  日期范围: {result['date_range']}")
    print()
    rows = [{
        "symbol": e["symbol"],
        "name": e["name"][:12],
        "生效日": e["date"],
        "比例": e["ratio"],
        "内容": e["content"][:20],
    } for e in events]
    print_display_table(rows, columns=["symbol", "name", "生效日", "比例", "内容"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="拆股/合股日历")
    parser.add_argument("--market", default=None, help="HK|US|CN|SG|...(留空=全市场)")
    parser.add_argument("--symbol", default=None, help="单标的过滤,如 AAPL.US")
    parser.add_argument("--watchlist", action="store_true", help="仅自选股(与 --symbol 互斥)")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--count", type=int, default=50, help="返回事件数上限(默认 50)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_split_calendar(
            market=args.market, symbol=args.symbol, watchlist=args.watchlist,
            start=args.start, end=args.end, count=args.count, output_json=args.output_json,
        )
    except Exception as e:
        print_error("获取拆股日历", str(e))
        sys.exit(1)
