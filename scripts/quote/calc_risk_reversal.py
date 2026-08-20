"""25-Delta 风险逆转(Risk Reversal)= IV(25Δ Call) - IV(25Δ Put)。

期权市场最常用的偏度标准化指标(外汇/股票通用):
  RR > 0: 上行需求占优(市场押注/对冲上涨)
  RR < 0: 下行保护占优(恐慌 put 买盘,常见于财报/危机前)
  与 get_vol_smile 的差异: 用固定 delta(0.25)定位行权价,跨标的/跨时间可比。

计算: 对每个 strike 用 BS 算 delta,取 |delta| 最接近 0.25 的 Call/Put 各自 IV。

用法:
    python calc_risk_reversal.py AAPL.US --date 2026-09-18
    python calc_risk_reversal.py AAPL.US --delta 0.25 --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    bs_greeks,
    days_to_years,
    get_option_chain,
    get_option_expirations,
    get_underlying_price,
    is_empty,
    print_error,
    print_json,
    to_float,
)


def analyze(symbol: str, date: str | None = None, target_delta: float = 0.25,
            rate: float = 0.045, output_json: bool = False) -> dict:
    price = get_underlying_price(symbol)
    if not price:
        raise ValueError(f"无法获取 {symbol} 现价")
    if date is None:
        exps = get_option_expirations(symbol)
        if not exps:
            raise ValueError(f"{symbol} 无可用到期日")
        date = exps[0]

    chain = get_option_chain(symbol, date)
    if is_empty(chain):
        raise ValueError(f"{symbol} 在 {date} 无期权链")

    T = days_to_years(date)
    if T <= 0:
        raise ValueError(f"到期日 {date} 已过期")

    # 找 |delta| 最接近 target 的 call 和 put
    best_call = best_put = None
    for r in chain:
        s = to_float(r.get("strike"))
        if not s:
            continue
        civ = to_float(r.get("call_iv"))
        piv = to_float(r.get("put_iv"))
        if civ and civ > 0:
            d = abs(bs_greeks(price, s, T, rate, civ, "C")["delta"])
            if d <= target_delta * 1.5 and (best_call is None or abs(d - target_delta) < best_call[0]):
                best_call = (abs(d - target_delta), s, d, civ)
        if piv and piv > 0:
            d = abs(bs_greeks(price, s, T, rate, piv, "P")["delta"])
            if d <= target_delta * 1.5 and (best_put is None or abs(d - target_delta) < best_put[0]):
                best_put = (abs(d - target_delta), s, d, piv)

    if not best_call or not best_put:
        raise ValueError(f"{date} 链上找不到 |delta|≈{target_delta} 的合约(流动性不足或 IV 缺失)")

    rr = best_call[3] - best_put[3]  # 小数
    rr_pp = rr * 100
    if rr_pp > 1:
        label = "正向(上行需求占优)"
    elif rr_pp < -1:
        label = "负向(下行保护占优,市场担忧下跌)"
    else:
        label = "中性"

    result = {
        "symbol": symbol,
        "expiry": date,
        "underlying_price": price,
        "target_delta": target_delta,
        "call_25d": {"strike": best_call[1], "delta": round(best_call[2], 3),
                     "iv_pct": round(best_call[3] * 100, 2)},
        "put_25d": {"strike": best_put[1], "delta": round(best_put[2], 3),
                    "iv_pct": round(best_put[3] * 100, 2)},
        "risk_reversal_pp": round(rr_pp, 2),
        "label": label,
        "note": "RR = IV(25Δ Call) - IV(25Δ Put),单位百分点。delta 用 BS 计算(IV 来自 chain)。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 风险逆转(到期 {date},目标 Δ={target_delta})")
    c, p = result["call_25d"], result["put_25d"]
    print(f"  {target_delta:.2f}Δ Call: K={c['strike']} IV={c['iv_pct']}%")
    print(f"  {target_delta:.2f}Δ Put:  K={p['strike']} IV={p['iv_pct']}%")
    print(f"  Risk Reversal = {c['iv_pct']} - {p['iv_pct']} = {rr_pp:+.2f}pp → {label}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="25-Delta 风险逆转(偏度标准化指标)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--date", default=None, help="到期日 YYYY-MM-DD(默认最近)")
    parser.add_argument("--delta", type=float, default=0.25, help="目标 delta(默认 0.25)")
    parser.add_argument("--rate", type=float, default=0.045, help="无风险利率")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, date=args.date, target_delta=args.delta,
                rate=args.rate, output_json=args.output_json)
    except Exception as e:
        print_error("风险逆转", str(e))
        sys.exit(1)
