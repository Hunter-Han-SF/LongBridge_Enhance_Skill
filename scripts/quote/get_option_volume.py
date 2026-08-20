"""获取期权成交量与 P/C 比率(A 档·原生)。

对应 Futu: get_option_market_statistic(部分) + get_option_underlying_his_statistic(P/C 比率)
数据源:
  - longbridge option volume <SYMBOL>        → 实时 Call/Put 成交量
  - longbridge option volume daily <SYMBOL>  → 每日 P/C 比率 + 成交量/持仓量时间序列

⚠️ 仅支持美股(US OPRA)。港股返回空。

用法:
    # 实时成交量快照
    python get_option_volume.py AAPL.US
    python get_option_volume.py AAPL.US --json

    # 每日 P/C 比率时间序列(默认 20 个交易日)
    python get_option_volume.py AAPL.US --daily
    python get_option_volume.py AAPL.US --daily --count 60
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_option_volume_daily,
    get_option_volume_realtime,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_int,
)


def _ts_to_date(ts: Any) -> str:
    """Unix 时间戳 → YYYY-MM-DD。"""
    n = to_int(ts)
    if n is None:
        return str(ts)
    return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%d")


def get_volume(
    symbol: str,
    daily: bool = False,
    count: int = 20,
    output_json: bool = False,
) -> dict | list:
    if daily:
        rows = get_option_volume_daily(symbol, count=count)
        # 加可读日期列(键名带 _utc,明确时区)
        for r in rows:
            r["date_utc"] = _ts_to_date(r.get("timestamp"))
        if output_json:
            print_json({"symbol": symbol, "daily": True, "data": rows})
            return rows
        if is_empty(rows):
            print(f"无每日成交量数据。仅美股支持,请确认 {symbol} 是美股标的。")
            return rows
        cols = ["date_utc", "total_call_volume", "total_put_volume", "put_call_volume_ratio",
                "put_call_open_interest_ratio", "total_open_interest"]
        print(f"{symbol} 每日期权 P/C 比率(近 {count} 个交易日):")
        print_display_table(rows, columns=cols)
        return rows
    else:
        snap = get_option_volume_realtime(symbol)
        if output_json:
            print_json({"symbol": symbol, "data": snap})
            return snap
        if is_empty(snap):
            print(f"无实时成交量数据。仅美股支持,请确认 {symbol} 是美股标的。")
            return snap
        print(f"{symbol} 实时期权成交量:")
        print_display_table([snap], columns=["call_volume", "put_volume", "pc_ratio"])
        return snap


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="获取期权成交量与 P/C 比率(仅美股)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--daily", action="store_true", help="查每日时间序列(默认查实时快照)")
    parser.add_argument("--count", type=int, default=20, help="每日序列天数(默认 20)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        get_volume(args.symbol, daily=args.daily, count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取期权成交量", str(e))
        sys.exit(1)
