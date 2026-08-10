"""期权行权概率(ITM probability,B 档·计算)。

对应 Futu: get_option_exercise_probability

行权概率的两种计算方式:
  1. delta 近似: |delta|(业界常用,假设对数正态分布)
  2. BS 闭式解: N(d2)(Call) 或 N(-d2)(Put),即到期时 ITM 的风险中性概率

本脚本两种都给。注意这是"风险中性概率",与真实世界概率不同(不含风险溢价)。

用法:
    python calc_exercise_prob.py AAPL.US 2026-08-14 315 CALL
    python calc_exercise_prob.py AAPL.US 2026-08-14 300 PUT --json
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    _norm_cdf,
    build_occ_code,
    days_to_years,
    get_option_chain,
    get_underlying_price,
    print_error,
    print_json,
    to_float,
)


def exercise_prob(
    underlying: str,
    expiry: str,
    strike: float,
    option_type: str,
    rate: float = 0.045,
    output_json: bool = False,
) -> dict:
    cp = "C" if option_type.upper() in ("CALL", "C") else "P"

    price = get_underlying_price(underlying)
    if not price:
        raise ValueError(f"无法获取 {underlying} 现价")

    # 取 IV
    chain = get_option_chain(underlying, expiry)
    iv = None
    delta_approx = None
    iv_key = "call_iv" if cp == "C" else "put_iv"
    for r in chain:
        s = to_float(r.get("strike"))
        if s is not None and abs(s - strike) < 0.001:
            iv = to_float(r.get(iv_key))
            break
    if not iv or iv <= 0:
        raise ValueError(f"chain 中无 {strike} 行权价的有效 IV")

    T = days_to_years(expiry)
    # BS d2
    d1 = (math.log(price / strike) + (rate + 0.5 * iv ** 2) * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)

    if cp == "C":
        prob_bs = _norm_cdf(d2)        # Call ITM = N(d2)
        delta = _norm_cdf(d1)
    else:
        prob_bs = _norm_cdf(-d2)       # Put ITM = N(-d2)
        delta = _norm_cdf(d1) - 1

    prob_delta = abs(delta)  # |delta| 近似

    result = {
        "occ_symbol": build_occ_code(*parse_ul(underlying), expiry, strike, option_type),
        "underlying": underlying,
        "expiry": expiry,
        "strike": strike,
        "type": "CALL" if cp == "C" else "PUT",
        "underlying_price": price,
        "iv_pct": round(iv * 100, 2),
        "days_to_expiry": round(T * 365),
        "exercise_prob_bs": round(prob_bs * 100, 2),       # BS 闭式解(%)
        "exercise_prob_delta": round(prob_delta * 100, 2), # |delta| 近似(%)
        "method_note": "风险中性概率(BS/|delta|),不含风险溢价,非真实世界概率",
    }

    if output_json:
        print_json(result)
        return result

    print(f"行权概率: {result['occ_symbol']}")
    print(f"  到期 {expiry}({result['days_to_expiry']:.0f}天)  现价 {price}  IV {result['iv_pct']}%")
    print(f"  BS 闭式解:   {result['exercise_prob_bs']}%")
    print(f"  |delta| 近似: {result['exercise_prob_delta']}%")
    print(f"  注: 风险中性概率,与真实世界概率不同")
    return result


def parse_ul(underlying: str):
    from common import parse_underlying
    t, _ = parse_underlying(underlying)
    return (t,)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="期权行权(ITM)概率")
    parser.add_argument("underlying", help="正股代码")
    parser.add_argument("expiry", help="到期日 YYYY-MM-DD")
    parser.add_argument("strike", type=float, help="行权价")
    parser.add_argument("option_type", help="CALL / PUT")
    parser.add_argument("--rate", type=float, default=0.045, help="无风险利率")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        exercise_prob(args.underlying, args.expiry, args.strike, args.option_type,
                      rate=args.rate, output_json=args.output_json)
    except Exception as e:
        print_error("行权概率", str(e))
        sys.exit(1)
