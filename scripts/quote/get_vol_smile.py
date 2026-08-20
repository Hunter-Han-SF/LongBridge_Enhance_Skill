"""期权波动率微笑/偏度(B 档·计算)。

对应 Futu: get_option_volatility(扩展,按 strike 列出 IV)
数据源: longbridge option chain --date(每个 strike 已含 call_iv/put_iv)

输出每个行权价的 call_iv/put_iv,以及偏度指标(OTM put IV - ATM IV)。

用法:
    python get_vol_smile.py AAPL.US --expiry 2026-09-18
    python get_vol_smile.py AAPL.US --expiry 2026-09-18 --near-atm 313
    python get_vol_smile.py AAPL.US --expiry 2026-09-18 --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    find_atm_strike,
    get_option_chain,
    get_option_expirations,
    get_underlying_price,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def smile(
    symbol: str,
    expiry: str | None = None,
    near_atm: float | None = None,
    atm_range: float = 0.20,
    output_json: bool = False,
) -> dict:
    if expiry is None:
        expirations = get_option_expirations(symbol)
        if not expirations:
            raise ValueError(f"{symbol} 无可用到期日")
        expiry = expirations[0]

    price = near_atm if near_atm is not None else get_underlying_price(symbol)
    chain = get_option_chain(symbol, expiry)

    # 过滤掉 IV=0(无成交/无效)的行,并按 ATM 范围过滤
    rows = []
    for r in chain:
        s = to_float(r.get("strike"))
        civ = to_float(r.get("call_iv"))
        piv = to_float(r.get("put_iv"))
        if s is None:
            continue
        if price and not (price * (1 - atm_range) <= s <= price * (1 + atm_range)):
            continue
        # 至少有一边 IV 有效
        if (civ is None or civ == 0) and (piv is None or piv == 0):
            continue
        rows.append({
            "strike": s,
            "call_iv_pct": round(civ * 100, 2) if civ else None,
            "put_iv_pct": round(piv * 100, 2) if piv else None,
            "moneyness": round(s / price, 3) if price else None,  # K/S, <1=ITM call, >1=OTM call
        })

    if is_empty(rows):
        raise ValueError(f"{expiry} 无有效 IV 数据")

    atm_strike = find_atm_strike(chain, price) if price else rows[0]["strike"]
    atm_call_iv = next((r["call_iv_pct"] for r in rows if r["strike"] == atm_strike), None)

    # 偏度:OTM put(最低 strike 的 put_iv)- ATM put_iv
    put_ivs = [(r["strike"], r["put_iv_pct"]) for r in rows if r["put_iv_pct"]]
    skew = None
    if len(put_ivs) >= 2 and atm_strike:
        # OTM put = moneyness 最低(最深 ITM put / 最 OTM put 取决于定义)
        # 标准:取 delta 约 -0.25 的 put,这里用 0.85×price 附近近似
        otm_target = price * 0.85 if price else atm_strike
        otm_put_iv = min(put_ivs, key=lambda x: abs(x[0] - otm_target))[1]
        atm_put_iv = next((iv for s, iv in put_ivs if s == atm_strike), atm_call_iv)
        if atm_put_iv:
            skew = round(otm_put_iv - atm_put_iv, 2)

    result = {
        "symbol": symbol,
        "expiry": expiry,
        "underlying_price": price,
        "atm_strike": atm_strike,
        "atm_iv_pct": atm_call_iv,
        "put_skew_pp": skew,  # OTM put IV - ATM IV,单位百分点(pp)
        "skew_shape": ("positive (downside fear)" if skew is not None and skew > 1 else
                       "negative (upside demand)" if skew is not None and skew < -1 else
                       ("flat" if skew is not None else "unknown")),
        "smile": rows,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 波动率微笑(到期 {expiry},现价 {price})")
    print(f"  ATM 行权价: {atm_strike}  ATM IV: {atm_call_iv}%")
    print(f"  Put 偏度(OTM put - ATM): {skew} pp  → {result['skew_shape']}")
    print()
    print_display_table(rows, columns=["strike", "moneyness", "call_iv_pct", "put_iv_pct"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="期权波动率微笑/偏度")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--expiry", default=None, help="到期日 YYYY-MM-DD(默认最近)")
    parser.add_argument("--near-atm", type=float, default=None, help="正股现价(用于过滤 ATM 附近)")
    parser.add_argument("--atm-range", type=float, default=0.20, help="显示范围 ±比例(默认 0.20)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        smile(args.symbol, expiry=args.expiry, near_atm=args.near_atm,
              atm_range=args.atm_range, output_json=args.output_json)
    except Exception as e:
        print_error("波动率微笑", str(e))
        sys.exit(1)
