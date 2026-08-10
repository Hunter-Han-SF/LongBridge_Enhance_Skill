"""获取财报发布日历。

对应 Longbridge CLI: finance-calendar report --market --symbol --start --end
官方 skill 无此加工分析。

每个财报事件含:
  - counter_id / counter_name: 标的
  - date / date_type: 发布时间(如"盘前"/"盘后") + 时区
  - data_kv: 结构化数据(estimate_eps/actual_eps/estimate_revenue/actual_revenue)
    value_raw 为空 = "待公布"(TBD),有值 = 已公布
  - ext.industry: 所属行业

用法:
    python get_earnings_calendar.py                          # 全市场近期
    python get_earnings_calendar.py --market US              # 仅美股
    python get_earnings_calendar.py --market US --count 30
    python get_earnings_calendar.py --symbol AAPL.US         # 单标的
    python get_earnings_calendar.py --market HK --watchlist  # 仅自选股
    python get_earnings_calendar.py --json
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

# data_kv 的 type 字段含义
KV_LABELS = {
    "estimate_eps": "预测EPS",
    "actual_eps": "实际EPS",
    "estimate_revenue": "预测营收",
    "actual_revenue": "实际营收",
}


def _parse_data_kv(infos: list[dict]) -> dict:
    """从 info.data_kv 提取结构化指标 → {type: {label, value, value_raw}}。"""
    out = {}
    kv_list = infos.get("data_kv", []) if isinstance(infos, dict) else []
    for kv in kv_list:
        if not isinstance(kv, dict):
            continue
        t = kv.get("type")
        if t:
            out[t] = {
                "label": KV_LABELS.get(t, t),
                "value": kv.get("value", ""),
                "value_raw": kv.get("value_raw", ""),
            }
    return out


def _flatten_events(buckets: list[dict]) -> list[dict]:
    """把按日期分桶的日历展平成事件列表。"""
    events = []
    for b in buckets:
        for info in b.get("infos", []):
            if not isinstance(info, dict):
                continue
            kv = _parse_data_kv(info)
            ext = info.get("ext") or {}
            # 是否已公布: actual_eps 或 actual_revenue 有 value_raw 视为已公布
            published = any(
                kv.get(t, {}).get("value_raw") not in ("", None)
                for t in ("actual_eps", "actual_revenue")
            )
            events.append({
                "symbol": counter_id_to_symbol(info.get("counter_id", "")) or info.get("counter_id", ""),
                "name": info.get("counter_name", ""),
                "date": info.get("date", ""),
                "date_type": info.get("date_type", ""),
                "industry": ext.get("industry", ""),
                "published": published,
                "estimate_eps": kv.get("estimate_eps", {}).get("value", ""),
                "actual_eps": kv.get("actual_eps", {}).get("value", ""),
                "estimate_revenue": kv.get("estimate_revenue", {}).get("value", ""),
                "actual_revenue": kv.get("actual_revenue", {}).get("value", ""),
                "content": info.get("content", ""),
            })
    return events


def fetch_earnings_calendar(
    market: str | None = None,
    symbol: str | None = None,
    watchlist: bool = False,
    start: str | None = None,
    end: str | None = None,
    count: int = 30,
    output_json: bool = False,
) -> dict:
    filter_arg = "watchlist" if watchlist else None
    # filter 与 symbol 互斥(symbol 优先)
    if symbol:
        filter_arg = None

    buckets = get_finance_calendar(
        category="report", market=market, symbol=symbol, filter=filter_arg,
        start=start, end=end, count=count,
    )
    if is_empty(buckets):
        scope = symbol or (f"{market or '全市场'}" + (" 自选股" if watchlist else ""))
        raise ValueError(f"无财报日历数据({scope})。尝试调整 market/date 范围。")

    events = _flatten_events(buckets)

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
    published = sum(1 for e in events if e["published"])
    print(f"{scope} 财报日历({len(events)} 个事件,已公布 {published},待公布 {len(events) - published})")
    if buckets:
        print(f"  日期范围: {result['date_range']}")
    print()

    # 精简表格(只显示关键列)
    rows = [{
        "symbol": e["symbol"],
        "name": e["name"][:12],
        "发布时间": e["date"],
        "盘前/后": e["date_type"],
        "预测EPS": e["estimate_eps"],
        "实际EPS": e["actual_eps"],
        "状态": "✅已公布" if e["published"] else "⏳待公布",
    } for e in events]
    print_display_table(rows, columns=["symbol", "name", "发布时间", "盘前/后", "预测EPS", "实际EPS", "状态"])
    print("\n提示: 营收数据见 --json 输出的 estimate_revenue/actual_revenue 字段")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="财报发布日历")
    parser.add_argument("--market", default=None, help="HK|US|CN|SG|...(留空=全市场)")
    parser.add_argument("--symbol", default=None, help="单标的过滤,如 AAPL.US")
    parser.add_argument("--watchlist", action="store_true", help="仅自选股(与 --symbol 互斥)")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--count", type=int, default=30, help="返回事件数上限(默认 30)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_earnings_calendar(
            market=args.market, symbol=args.symbol, watchlist=args.watchlist,
            start=args.start, end=args.end, count=args.count, output_json=args.output_json,
        )
    except Exception as e:
        print_error("获取财报日历", str(e))
        sys.exit(1)
