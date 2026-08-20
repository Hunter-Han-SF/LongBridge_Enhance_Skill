"""多腿组合期权 Greeks 加权(B 档·计算)。

对应 Futu: get_option_quote(多腿) / get_option_strategy_analysis(Greeks 部分)

输入: 多条期权腿 [{underlying, expiry, strike, type, action, quantity}, ...]
组合 Greeks = Σ (单腿 Greeks × 方向符号 × 数量)
  - BUY 的腿用 +1,SELL 的腿用 -1
  - 支持正股腿(type=STOCK,delta=100 股/手,其余 Greeks 为 0),
    可直接分析 get_option_strategy.py 生成的 COLLAR / COVERED_CALL

⚠️ Greeks 为 BS 计算值(IV 来自 chain)。仅支持同标的、同到期日的多腿组合。

用法:
    # Straddle: 买入 1 张 ATM Call + 1 张 ATM Put
    python calc_option_greeks.py '[{"underlying":"AAPL.US","expiry":"2026-08-14","strike":315,"type":"CALL","action":"BUY","quantity":1},{"underlying":"AAPL.US","expiry":"2026-08-14","strike":315,"type":"PUT","action":"BUY","quantity":1}]'
    python calc_option_greeks.py legs.json --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import print_error, print_json  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from get_option_quote import get_quote  # noqa: E402


def _load_legs(source: str) -> list[dict]:
    """从 JSON 字符串或文件路径加载腿列表。"""
    if os.path.isfile(source):
        with open(source, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(source)


def calc_portfolio_greeks(legs: list[dict], rate: float = 0.045) -> dict:
    if not legs:
        raise ValueError("腿列表为空")

    detail = []
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    sign_map = {"BUY": 1, "SELL": -1}

    for leg in legs:
        ul = leg["underlying"]
        expiry = leg["expiry"]
        strike = float(leg["strike"])
        ot = str(leg["type"]).upper()
        action = leg.get("action", "BUY").upper()
        qty = float(leg.get("quantity", 1))
        sign = sign_map.get(action, 1)

        # 正股腿(COLLAR/COVERED_CALL 策略生成):delta = 100 股/手,其余 Greeks 恒为 0
        if ot in ("STOCK", "SHARE", "UNDERLYING"):
            weighted = {"delta": 100.0 * sign * qty, "gamma": 0.0,
                        "theta": 0.0, "vega": 0.0, "rho": 0.0}
            for k in totals:
                totals[k] += weighted[k]
            detail.append({
                "leg": f"{action} {qty}× {ul} 正股",
                "iv_pct": None,
                "delta": round(weighted["delta"], 4),
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
            })
            continue

        q = get_quote(ul, expiry, strike, ot, rate=rate, output_json=False, quiet=True)
        # get_quote 会打印;我们只取 greeks。为避免重复输出,这里静默重算
        greeks = q["greeks"]
        if not greeks:
            raise ValueError(f"无法计算 {ul} {expiry} {strike} {ot} 的 Greeks(可能缺 IV 或到期日已过期)")

        weighted = {k: greeks[k] * sign * qty for k in totals}
        for k in totals:
            totals[k] += weighted[k]

        detail.append({
            "leg": f"{action} {qty}× {ul} {expiry} {strike} {ot}",
            "iv_pct": q["iv_pct"],
            "delta": round(weighted["delta"], 4),
            "gamma": round(weighted["gamma"], 4),
            "theta": round(weighted["theta"], 4),
            "vega": round(weighted["vega"], 4),
        })

    return {
        "legs": len(legs),
        "detail": detail,
        "portfolio_greeks": {k: round(v, 4) for k, v in totals.items()},
        "interpretation": _interpret(totals),
        "note": "组合 Greeks 为 BS 计算加权值,theta=/日,vega=/1%IV",
    }


def _interpret(g: dict) -> str:
    parts = []
    if abs(g["delta"]) < 0.1:
        parts.append("Delta 中性(方向风险小)")
    elif g["delta"] > 0:
        parts.append(f"看多敞口(delta={g['delta']:.2f})")
    else:
        parts.append(f"看空敞口(delta={g['delta']:.2f})")
    if g["theta"] > 0:
        parts.append(f"时间衰减有利(theta=+{g['theta']:.2f}/日)")
    else:
        parts.append(f"时间衰减不利(theta={g['theta']:.2f}/日)")
    if g["vega"] > 0:
        parts.append(f"看多波动(vega=+{g['vega']:.2f})")
    else:
        parts.append(f"看空波动(vega={g['vega']:.2f})")
    return "; ".join(parts)


def main():
    parser = argparse.ArgumentParser(description="多腿组合期权 Greeks 加权")
    parser.add_argument("legs", help="腿列表:JSON 字符串或 .json 文件路径")
    parser.add_argument("--rate", type=float, default=0.045, help="无风险利率")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        legs = _load_legs(args.legs)
        result = calc_portfolio_greeks(legs, rate=args.rate)
        if args.output_json:
            print_json(result)
        else:
            print(f"组合 Greeks({result['legs']} 腿)")
            print("  各腿明细:")
            for d in result["detail"]:
                iv_str = f"IV={d['iv_pct']}%" if d.get("iv_pct") is not None else "正股"
                print(f"    {d['leg']}  {iv_str}  delta={d['delta']} theta={d['theta']} vega={d['vega']}")
            pg = result["portfolio_greeks"]
            print(f"  组合计:")
            print(f"    delta = {pg['delta']}")
            print(f"    gamma = {pg['gamma']}")
            print(f"    theta = {pg['theta']} /日")
            print(f"    vega  = {pg['vega']} /1%IV")
            print(f"    rho   = {pg['rho']}")
            print(f"  解读: {result['interpretation']}")
    except Exception as e:
        print_error("组合 Greeks", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
