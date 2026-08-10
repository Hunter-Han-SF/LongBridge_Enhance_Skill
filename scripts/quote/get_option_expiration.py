"""获取期权到期日列表(A 档·原生)。

对应 Futu: get_option_expiration_date
数据源: longbridge option chain <SYMBOL>(不带 --date 时返回所有到期日)

用法:
    python get_option_expiration.py AAPL.US
    python get_option_expiration.py AAPL.US --json
    python get_option_expiration.py AAPL.US --limit 10
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_option_expirations,
    is_empty,
    print_display_table,
    print_error,
    print_json,
)


def get_option_expiration(symbol: str, limit: int | None = None, output_json: bool = False) -> list[str]:
    expirations = get_option_expirations(symbol)
    if limit:
        expirations = expirations[:limit]

    if output_json:
        print_json({"symbol": symbol, "data": expirations})
        return expirations

    if is_empty(expirations):
        print(f"无可用到期日。请确认 {symbol} 是否为支持期权的标的(美股 OPRA)。")
        return expirations

    rows = [{"#": i + 1, "expiry_date": d} for i, d in enumerate(expirations)]
    print(f"{symbol} 共 {len(expirations)} 个到期日:")
    print_display_table(rows, columns=["#", "expiry_date"])
    return expirations


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="获取期权到期日列表")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US / TSLA.US")
    parser.add_argument("--limit", type=int, default=None, help="只显示前 N 个到期日")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        get_option_expiration(args.symbol, limit=args.limit, output_json=args.output_json)
    except Exception as e:
        print_error("获取期权到期日", str(e))
        sys.exit(1)
