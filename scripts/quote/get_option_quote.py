"""单合约期权报价 + Greeks(A 档原生 + B 档 BS 计算)。

对应 Futu: get_option_quote / get_snapshot(期权)

数据策略(因 Longbridge option quote 对单合约返回空):
  1. 尝试 longbridge option quote <OCC>(原生,权限开通后可能有数据)
  2. 若空 → fallback: 从 chain 取该行权价的 IV/价格,用 Black-Scholes 自算 Greeks

⚠️ Greeks 为 BS 模型计算值(IV 来自 chain),与服务端 Greeks 可能有细微差异。
   theta 单位:每日;vega 单位:每 1% IV 变化;rho 单位:每 1% 利率变化。

用法:
    python get_option_quote.py AAPL.US 2026-08-14 315 CALL
    python get_option_quote.py AAPL.US 2026-08-14 315 CALL --json
    python get_option_quote.py AAPL.US 2026-08-14 315 CALL --rate 0.045
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    LongbridgeCliError,
    bs_greeks,
    bs_price,
    build_occ_code,
    days_to_years,
    get_option_chain,
    get_underlying_price,
    is_empty,
    parse_underlying,
    print_error,
    print_json,
    run_cli,
    to_float,
)


def get_quote(
    underlying: str,
    expiry: str,
    strike: float,
    option_type: str,
    rate: float = 0.045,
    output_json: bool = False,
    quiet: bool = False,
) -> dict:
    cp = "C" if option_type.upper() in ("CALL", "C") else "P"
    ticker, _ = parse_underlying(underlying)
    occ = build_occ_code(ticker, expiry, strike, option_type)

    # 1. 尝试原生 option quote
    native: dict | None = None
    try:
        data = run_cli("option", "quote", occ)
        if not is_empty(data) and isinstance(data, list) and data:
            native = data[0] if isinstance(data[0], dict) else None
    except LongbridgeCliError:
        pass

    # 2. 从 chain 取 IV + 价格(无论原生是否成功,chain 都有 IV)
    chain = get_option_chain(underlying, expiry)
    chain_row = None
    for r in chain:
        s = to_float(r.get("strike"))
        if s is not None and abs(s - strike) < 0.001:
            chain_row = r
            break

    iv = None
    last = None
    if chain_row:
        iv_key = "call_iv" if cp == "C" else "put_iv"
        last_key = "call_last" if cp == "C" else "put_last"
        iv = to_float(chain_row.get(iv_key))
        last = to_float(chain_row.get(last_key))

    # 3. 正股现价 + BS Greeks
    price = get_underlying_price(underlying)
    T = days_to_years(expiry)
    greeks = None
    bs_price_val = None
    if price and iv and iv > 0:
        greeks = bs_greeks(price, strike, T, rate, iv, cp)
        bs_price_val = bs_price(price, strike, T, rate, iv, cp)

    result = {
        "occ_symbol": occ,
        "underlying": underlying,
        "expiry": expiry,
        "strike": strike,
        "type": "CALL" if cp == "C" else "PUT",
        "underlying_price": price,
        "implied_volatility": iv,
        "iv_pct": round(iv * 100, 2) if iv else None,
        "last": last,
        "bs_theoretical_price": round(bs_price_val, 4) if bs_price_val else None,
        "rate": rate,
        "days_to_expiry": round(T * 365),
        "greeks": greeks,
        "native_quote": native is not None,  # 是否拿到了原生 option quote 数据
        "greeks_source": "native" if (native and native.get("delta")) else "black_scholes",
    }

    if output_json:
        print_json(result)
        return result

    if quiet:
        return result

    print(f"期权报价: {occ}")
    print(f"  类型: {'CALL' if cp == 'C' else 'PUT'}  行权价 {strike}  到期 {expiry}({result['days_to_expiry']:.0f}天)")
    print(f"  正股现价:    {price}")
    print(f"  隐含波动率:  {result['iv_pct']}%")
    print(f"  最新成交价:  {last}")
    print(f"  BS 理论价:   {result['bs_theoretical_price']}")
    src = "原生 option quote" if result["greeks_source"] == "native" else "Black-Scholes 计算(IV 来自 chain)"
    print(f"  Greeks 来源: {src}")
    if greeks:
        print(f"    delta = {greeks['delta']:.4f}")
        print(f"    gamma = {greeks['gamma']:.4f}")
        print(f"    theta = {greeks['theta']:.4f} /日")
        print(f"    vega  = {greeks['vega']:.4f} /1%IV")
        print(f"    rho   = {greeks['rho']:.4f} /1%rate")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="单合约期权报价 + Greeks")
    parser.add_argument("underlying", help="正股代码,如 AAPL.US")
    parser.add_argument("expiry", help="到期日 YYYY-MM-DD")
    parser.add_argument("strike", type=float, help="行权价")
    parser.add_argument("option_type", help="CALL / PUT / C / P")
    parser.add_argument("--rate", type=float, default=0.045, help="无风险利率(默认 0.045)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        get_quote(args.underlying, args.expiry, args.strike, args.option_type,
                  rate=args.rate, output_json=args.output_json)
    except Exception as e:
        print_error("期权报价", str(e))
        sys.exit(1)
