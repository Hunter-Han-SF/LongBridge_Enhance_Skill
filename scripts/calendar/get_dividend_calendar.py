"""获取除权除息(分红)日历。

对应 Longbridge CLI: finance-calendar dividend --market --symbol --start --end
官方 skill 无此加工分析。

每个分红事件含:
  - counter_id / counter_name: 标的
  - date: 除权除息日
  - ext.dividend_amount: 每股分红金额
  - ext.dividend_type: 分红类型(regular=常规/special=特别)
  - ext.payment_date: 派息日
  - ext.record_date: 登记日
  - ext.currency: 币种

用法:
    python get_dividend_calendar.py                          # 全市场近期
    python get_dividend_calendar.py --market US              # 仅美股
    python get_dividend_calendar.py --market HK --count 50
    python get_dividend_calendar.py --symbol AAPL.US         # 单标的
    python get_dividend_calendar.py --market US --watchlist  # 仅自选股
    python get_dividend_calendar.py --json
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
    to_float,
)


def _flatten_dividends(buckets: list[dict]) -> list[dict]:
    """展平分红事件。"""
    events = []
    for b in buckets:
        for info in b.get("infos", []):
            if not isinstance(info, dict):
                continue
            ext = info.get("ext") or {}
            amount = to_float(ext.get("dividend_amount"))
            events.append({
                "symbol": counter_id_to_symbol(info.get("counter_id", "")) or info.get("counter_id", ""),
                "name": info.get("counter_name", ""),
                "ex_date": info.get("date", ""),
                "amount": amount,
                "currency": ext.get("currency", ""),
                "type": ext.get("dividend_type", ""),
                "record_date": ext.get("record_date", ""),
                "payment_date": ext.get("payment_date", ""),
                "industry": ext.get("industry", ""),
                "content": info.get("content", ""),
            })
    return events


def fetch_dividend_calendar(
    market: str | None = None,
    symbol: str | None = None,
    watchlist: bool = False,
    start: str | None = None,
    end: str | None = None,
    count: int = 50,
    output_json: bool = False,
) -> dict:
    filter_arg = "watchlist" if watchlist else None
    if symbol:
        filter_arg = None

    buckets = get_finance_calendar(
        category="dividend", market=market, symbol=symbol, filter=filter_arg,
        start=start, end=end, count=count,
    )
    if is_empty(buckets):
        scope = symbol or (f"{market or '全市场'}" + (" 自选股" if watchlist else ""))
        raise ValueError(f"无分红日历数据({scope})。")

    events = _flatten_dividends(buckets)

    result = {
        "market": market or "ALL",
        "symbol": symbol,
        "filter": "watchlist" if watchlist else None,
        "date_range": f"{buckets[0]['date']} ~ {buckets[-1]['date']}" if buckets else "",
        "total_events": len(events),
        "events": events,
    }

    if output_json:
        print_json(result)
        return result

    scope = symbol or (f"{market or '全市场'}" + (" 自选股" if watchlist else ""))
    total_amount = sum(e["amount"] or 0 for e in events if e["amount"])
    print(f"{scope} 除权除息日历({len(events)} 个事件)")
    if buckets:
        print(f"  日期范围: {result['date_range']}")
    print()
    rows = [{
        "symbol": e["symbol"],
        "name": e["name"][:12],
        "除息日": e["ex_date"],
        "每股分红": f"{e['amount']} {e['currency']}" if e["amount"] else "",
        "类型": "常规" if e["type"] == "regular" else ("特别" if e["type"] == "special" else e["type"]),
        "派息日": e["payment_date"],
    } for e in events]
    print_display_table(rows, columns=["symbol", "name", "除息日", "每股分红", "类型", "派息日"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="除权除息(分红)日历")
    parser.add_argument("--market", default=None, help="HK|US|CN|SG|...(留空=全市场)")
    parser.add_argument("--symbol", default=None, help="单标的过滤,如 AAPL.US")
    parser.add_argument("--watchlist", action="store_true", help="仅自选股(与 --symbol 互斥)")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--count", type=int, default=50, help="返回事件数上限(默认 50)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_dividend_calendar(
            market=args.market, symbol=args.symbol, watchlist=args.watchlist,
            start=args.start, end=args.end, count=args.count, output_json=args.output_json,
        )
    except Exception as e:
        print_error("获取分红日历", str(e))
        sys.exit(1)
