"""解析/构造期权 OCC 代码(A 档·原生)。

对应 Futu: resolve_option_code
Longbridge 的 chain 不返回 OCC 代码,本脚本通过 build_occ_code() 直接构造,
再用 chain 数据验证该行权价/类型确实存在。

OCC 格式: <TICKER><YYMMDD><C|P><STRIKE×1000, 8位整数>
例: AAPL 2026-03-20 267.50 Call → AAPL260320C0267500

用法:
    python resolve_option_code.py --underlying AAPL.US --expiry 2026-09-18 --strike 315 --type CALL
    python resolve_option_code.py --underlying AAPL.US --expiry 2026-09-18 --strike 315 --type CALL --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    build_occ_code,
    get_option_chain,
    parse_underlying,
    print_error,
    print_json,
    to_float,
)


def resolve(
    underlying: str,
    expiry: str,
    strike: float,
    option_type: str,
    output_json: bool = False,
) -> dict:
    ticker, market = parse_underlying(underlying)
    occ = build_occ_code(ticker, expiry, strike, option_type)

    # 验证:拉 chain 看该行权价是否存在
    chain = get_option_chain(underlying, expiry)
    strike_found = None
    for row in chain:
        s = to_float(row.get("strike"))
        if s is not None and abs(s - strike) < 0.001:
            strike_found = row
            break

    result = {
        "occ_symbol": occ,
        "underlying": underlying,
        "ticker": ticker,
        "market": market,
        "expiry": expiry,
        "strike": strike,
        "type": option_type.upper(),
        "strike_exists": strike_found is not None,
    }
    if strike_found:
        if option_type.upper() in ("CALL", "C"):
            result["iv"] = to_float(strike_found.get("call_iv"))
            result["last"] = to_float(strike_found.get("call_last"))
        else:
            result["iv"] = to_float(strike_found.get("put_iv"))
            result["last"] = to_float(strike_found.get("put_last"))

    if output_json:
        print_json(result)
        return result

    print(f"OCC 期权代码: {occ}")
    print(f"  标的={underlying}  到期={expiry}  行权价={strike}  类型={option_type.upper()}")
    if strike_found:
        print(f"  ✓ 该行权价在 chain 中存在  IV={result.get('iv')}  最新价={result.get('last')}")
    else:
        # 列出最接近的行权价供参考
        nearby = []
        for row in chain:
            s = to_float(row.get("strike"))
            if s is not None:
                nearby.append((abs(s - strike), s))
        nearby.sort()
        if nearby:
            closest = [f"{s}" for _, s in nearby[:5]]
            print(f"  ⚠ 未找到精确行权价 {strike}。最接近的: {', '.join(closest)}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构造并验证期权 OCC 代码")
    parser.add_argument("--underlying", required=True, help="正股代码,如 AAPL.US")
    parser.add_argument("--expiry", required=True, help="到期日 YYYY-MM-DD")
    parser.add_argument("--strike", type=float, required=True, help="行权价")
    parser.add_argument("--type", required=True, help="期权类型 CALL/PUT/C/P")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        resolve(args.underlying, args.expiry, args.strike, args.type, output_json=args.output_json)
    except Exception as e:
        print_error("解析期权代码", str(e))
        sys.exit(1)
