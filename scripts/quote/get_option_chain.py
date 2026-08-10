"""获取期权链(A 档·原生)。

对应 Futu: get_option_chain
数据源: longbridge option chain <SYMBOL> --date <EXPIRY>
返回每个行权价的: strike / call_iv / put_iv / call_last / put_last / call_vol / put_vol / standard

注意:Longbridge CLI 的 chain 不返回 OCC 代码(symbol),需用 resolve_option_code.py 构造。
      chain 已含 IV,无需额外调 option quote。

用法:
    python get_option_chain.py AAPL.US --date 2026-09-18
    python get_option_chain.py AAPL.US --date 2026-09-18 --near-atm 313
    python get_option_chain.py AAPL.US --date 2026-09-18 --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_option_chain,
    is_empty,
    print_display_table,
    print_error,
    print_json,
)


def get_chain(
    symbol: str,
    expiry: str,
    near_atm: float | None = None,
    atm_range: float = 0.20,
    output_json: bool = False,
) -> list[dict]:
    rows = get_option_chain(symbol, expiry)

    # ATM 附近过滤(可选):near_atm 为正股现价,atm_range 为 ±20% 范围
    if near_atm is not None and rows:
        lo = near_atm * (1 - atm_range)
        hi = near_atm * (1 + atm_range)
        rows = [r for r in rows if lo <= r.get("strike", 0) <= hi]

    if output_json:
        print_json({"symbol": symbol, "expiry": expiry, "data": rows})
        return rows

    if is_empty(rows):
        print(f"无期权链数据。请确认 {symbol} 在 {expiry} 有挂牌期权。")
        return rows

    print(f"{symbol} 到期日 {expiry} 共 {len(rows)} 个行权价:")
    cols = ["strike", "call_last", "call_iv", "call_vol", "put_last", "put_iv", "put_vol", "standard"]
    print_display_table(rows, columns=cols)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="获取期权链(某到期日的所有行权价)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--date", required=True, help="到期日 YYYY-MM-DD")
    parser.add_argument("--near-atm", type=float, default=None,
                        help="只显示 ATM 附近的行权价(传入正股现价)")
    parser.add_argument("--atm-range", type=float, default=0.20,
                        help="ATM 范围 ±比例(默认 0.20 = ±20%%)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        get_chain(args.symbol, args.date, near_atm=args.near_atm,
                  atm_range=args.atm_range, output_json=args.output_json)
    except Exception as e:
        print_error("获取期权链", str(e))
        sys.exit(1)
