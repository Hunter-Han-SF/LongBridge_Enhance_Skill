"""获取宏观经济数据发布日历(利率/CPI/就业/PMI 等)。

对应 Longbridge CLI: finance-calendar macrodata --market --star(重要性) --start --end

每个事件含 data_kv(前值/预测值,公布后含实际值)。按指标查询历史用
scripts/sentiment/get_macro_data.py(维度互补:本脚本按日期,那个按指标)。

用法:
    python get_macro_calendar.py                          # 近期宏观事件
    python get_macro_calendar.py --market US
    python get_macro_calendar.py --market US --count 30
    python get_macro_calendar.py --json
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


def _flatten_macro(buckets: list[dict]) -> list[dict]:
    events = []
    for b in buckets:
        for info in b.get("infos", []):
            if not isinstance(info, dict):
                continue
            kv = {kv.get("type", ""): kv.get("value", "")
                  for kv in (info.get("data_kv") or []) if isinstance(kv, dict)}
            events.append({
                "name": info.get("content", ""),
                "date": info.get("date", ""),
                "datetime": info.get("datetime", ""),
                "previous": kv.get("previous", ""),
                "estimate": kv.get("estimate", ""),
                "actual": kv.get("actual", ""),
                "importance": (info.get("ext") or {}).get("importance", ""),
            })
    return events


def fetch_macro_calendar(
    market: str | None = None,
    start: str | None = None,
    end: str | None = None,
    count: int = 50,
    output_json: bool = False,
) -> dict:
    buckets = get_finance_calendar(category="macrodata", market=market,
                                   start=start, end=end, count=count)
    if is_empty(buckets):
        raise ValueError(f"近期无宏观事件({market or '全市场'})。")

    events = _flatten_macro(buckets)
    result = {
        "market": market or "ALL",
        "date_range": f"{buckets[0]['date']} ~ {buckets[-1]['date']}",
        "total_events": len(events),
        "events": events,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{market or '全市场'} 宏观经济数据日历({len(events)} 个事件)")
    print(f"  日期范围: {result['date_range']}")
    print()
    rows = [{
        "指标": e["name"][:28],
        "时间": e["date"],
        "前值": str(e["previous"])[:10],
        "预测": str(e["estimate"])[:10],
        "实际": str(e["actual"])[:10],
    } for e in events]
    print_display_table(rows, columns=["指标", "时间", "前值", "预测", "实际"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="宏观经济数据发布日历")
    parser.add_argument("--market", default=None, help="HK|US|CN|SG|EU|JP|...(留空=全市场)")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--count", type=int, default=50, help="返回事件数上限(默认 50)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_macro_calendar(market=args.market, start=args.start, end=args.end,
                             count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取宏观日历", str(e))
        sys.exit(1)
