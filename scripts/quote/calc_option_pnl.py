"""期权组合损益分析(B 档·计算)。

对应 Futu: get_option_strategy_analysis(损益部分)

计算到期时组合在不同正股价格下的损益,找出:
  - 盈亏平衡点(break-even)
  - 最大盈利 / 最大亏损
  - 到期价值曲线

注:本脚本计算"到期损益"(到期时的内在价值),不含时间价值。
    组合摆盘价(bid/ask)Longbridge 不提供,需用各腿 last price 估算净成本。

用法:
    # Bull call spread: 买 315 Call + 卖 325 Call
    python calc_option_pnl.py '[{"underlying":"AAPL.US","expiry":"2026-08-14","strike":315,"type":"CALL","action":"BUY","quantity":1},{"underlying":"AAPL.US","expiry":"2026-08-14","strike":325,"type":"CALL","action":"SELL","quantity":1}]'
    python calc_option_pnl.py legs.json --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_option_chain,
    get_underlying_price,
    print_error,
    print_json,
    to_float,
)


def _load_legs(source: str) -> list[dict]:
    if os.path.isfile(source):
        with open(source, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(source)


def _intrinsic(S: float, strike: float, cp: str) -> float:
    return max(S - strike, 0) if cp == "C" else max(strike - S, 0)


def analyze_pnl(legs: list[dict], output_json: bool = False) -> dict:
    if not legs:
        raise ValueError("腿列表为空")

    underlying = legs[0]["underlying"]
    expiry = legs[0]["expiry"]
    price = get_underlying_price(underlying)
    if not price:
        raise ValueError(f"无法获取 {underlying} 现价")

    # 取各腿的 last price 作为成本/收入
    chain = get_option_chain(underlying, expiry)
    sign_map = {"BUY": 1, "SELL": -1}

    leg_costs = []
    total_cost = 0.0
    for leg in legs:
        strike = float(leg["strike"])
        cp = "C" if leg["type"].upper() in ("CALL", "C") else "P"
        action = leg.get("action", "BUY").upper()
        qty = float(leg.get("quantity", 1))
        last_key = "call_last" if cp == "C" else "put_last"
        last = None
        for r in chain:
            s = to_float(r.get("strike"))
            if s is not None and abs(s - strike) < 0.001:
                last = to_float(r.get(last_key))
                break
        if last is None:
            raise ValueError(f"chain 中无 {strike} 行权价的 {last_key}")
        sign = sign_map[action]
        cost = last * sign * qty * 100  # 美股期权每张 100 股
        total_cost += cost
        leg_costs.append({"leg": f"{action} {qty}× {strike} {leg['type']}", "last": last, "cost": round(cost, 2)})

    # 到期损益曲线:在现价 ±30% 范围扫描
    lo_price = price * 0.7
    hi_price = price * 1.3
    # 步长:用更细的 0.1 精确定位盈亏平衡(粗扫描会在拐点处漏掉/偏差)
    n_points = 400
    step = (hi_price - lo_price) / n_points
    curve = []
    break_evens = []
    prev_S = None
    prev_pnl = None
    S = lo_price
    while S <= hi_price + 0.01:
        # 组合到期价值
        value = 0.0
        for leg in legs:
            strike = float(leg["strike"])
            cp = "C" if leg["type"].upper() in ("CALL", "C") else "P"
            action = leg.get("action", "BUY").upper()
            qty = float(leg.get("quantity", 1))
            sign = sign_map[action]
            value += _intrinsic(S, strike, cp) * sign * qty * 100
        pnl = value - total_cost
        curve.append({"price": round(S, 2), "pnl": round(pnl, 2)})
        # 检测过零点 + 线性插值精确定位
        if prev_pnl is not None and ((prev_pnl < 0 < pnl) or (prev_pnl > 0 > pnl)):
            # 线性插值: be = prev_S + (0 - prev_pnl) × (S - prev_S) / (pnl - prev_pnl)
            be = prev_S + (0 - prev_pnl) * (S - prev_S) / (pnl - prev_pnl)
            break_evens.append(round(be, 2))
        prev_S = S
        prev_pnl = pnl
        S += step

    # 最大盈亏(在扫描范围内)
    pnls = [c["pnl"] for c in curve]
    max_profit = max(pnls) if pnls else 0
    max_loss = min(pnls) if pnls else 0

    # 判断是否有限
    # 简单启发:看两端的价格点
    is_profit_capped = curve[-1]["pnl"] < max_profit * 0.9 and abs(curve[-1]["pnl"]) < abs(max_loss) * 2
    is_loss_capped = curve[0]["pnl"] > max_loss * 0.9 and curve[-1]["pnl"] > max_loss * 0.9

    result = {
        "underlying": underlying,
        "expiry": expiry,
        "underlying_price": price,
        "total_cost": round(total_cost, 2),
        "cost_per_share": round(total_cost / 100, 4),
        "net_credit": total_cost < 0,  # 净收入(卖方策略)
        "break_even_points": break_evens,
        "max_profit": round(max_profit, 2) if not is_profit_capped else f"{round(max_profit,2)} (有限)",
        "max_loss": round(max_loss, 2) if not is_loss_capped else f"{round(max_loss,2)} (有限)",
        "legs_detail": leg_costs,
        "curve_points": len(curve),
        "note": "到期损益(基于各腿 last price 估算成本,不含时间价值/组合摆盘价)",
    }

    if output_json:
        print_json(result)
        return result

    print(f"组合损益分析({len(legs)} 腿,到期 {expiry})")
    print(f"  正股现价: {price}")
    print(f"  净成本:   ${total_cost} ({'净支出' if total_cost > 0 else '净收入'})")
    print(f"  盈亏平衡: {break_evens}")
    print(f"  最大盈利: {result['max_profit']}")
    print(f"  最大亏损: {result['max_loss']}")
    print(f"  各腿: ")
    for lc in leg_costs:
        print(f"    {lc['leg']}  last={lc['last']}  成本={lc['cost']}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="期权组合到期损益分析")
    parser.add_argument("legs", help="腿列表:JSON 字符串或 .json 文件路径")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        legs = _load_legs(args.legs)
        analyze_pnl(legs, output_json=args.output_json)
    except Exception as e:
        print_error("损益分析", str(e))
        sys.exit(1)
