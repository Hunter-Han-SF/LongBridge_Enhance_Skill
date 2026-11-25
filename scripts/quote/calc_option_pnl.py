"""期权组合损益分析(B 档·计算)。

对应 Futu: get_option_strategy_analysis(损益部分)

计算到期时组合在不同正股价格下的损益,找出:
  - 盈亏平衡点(break-even)
  - 最大盈利 / 最大亏损
  - 到期价值曲线

注:本脚本计算"到期损益"(到期时的内在价值),不含时间价值。
    组合摆盘价(bid/ask)Longbridge 不提供,需用各腿 last price 估算净成本。
    行权价当日无成交时 last=0(不是免费期权):依次改用腿内 "price"(手动指定,
    如 {"price": 0.15})或 chain IV 反推的 BS 理论价(标注为估算),都没有则报错。
    支持正股腿(type=STOCK,成本与到期价值直接用正股价),
    可直接分析 get_option_strategy.py 生成的 COLLAR / COVERED_CALL。

用法:
    # Bull call spread: 买 315 Call + 卖 325 Call
    python calc_option_pnl.py '[{"underlying":"AAPL.US","expiry":"2026-08-14","strike":315,"type":"CALL","action":"BUY","quantity":1},{"underlying":"AAPL.US","expiry":"2026-08-14","strike":325,"type":"CALL","action":"SELL","quantity":1}]'
    python calc_option_pnl.py legs.json --json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    bs_price,
    days_to_years,
    get_option_chain,
    get_underlying_price,
    get_underlying_price_info,
    price_source_note,
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


def _resolve_leg_price(row, last_key, iv_key, leg, spot, strike, cp, expiry, rate) -> tuple[float, str]:
    """期权腿的成本价 → (价格, 来源: manual / last / bs_from_iv)。

    chain 只有最新成交价、没有买卖价:行权价当日无成交时 last 为 0(实测 AAPL
    2026-11-24 的 80 档里有 16 档),那不是"免费期权"。依次取:
      ① 腿里显式给的 price —— 实际成交价,或自己假设的价格;
      ② chain 的 last(> 0);
      ③ chain IV 反推的 BS 理论价(标注为估算)。
    都没有则报错。
    """
    manual = leg.get("price")
    if manual is not None:
        value = to_float(manual)
        if value is None or not math.isfinite(value) or value < 0:
            raise ValueError(f"腿 {strike} {leg.get('type')} 的 price 必须为非负有限数")
        return value, "manual"
    if row is None:
        raise ValueError(
            f"chain 中没有 {strike} {leg.get('type')} 这一档(非标准合约或已摘牌),无法取成本;"
            f"请在该腿 JSON 里用 \"price\" 指定,如 {{\"price\": 0.15}}")
    last = to_float(row.get(last_key))
    if last is not None and last > 0:
        return last, "last"
    iv = to_float(row.get(iv_key))
    if iv and iv > 0 and spot and spot > 0:
        T = days_to_years(expiry)
        if T > 0:
            try:
                return bs_price(spot, strike, T, rate, iv, cp), "bs_from_iv"
            except ValueError:
                pass
    raise ValueError(
        f"chain 中 {strike} {leg.get('type')} 无有效成交价(last=0,当日无成交),"
        f"也没有可用 IV,无法估算该腿成本;请在该腿 JSON 里用 \"price\" 指定,如 {{\"price\": 0.15}}")


def analyze_pnl(
    legs: list[dict],
    output_json: bool = False,
    rate: float = 0.045,
    *,
    quiet: bool = False,
    underlying_price: float | None = None,
    chain: list[dict] | None = None,
) -> dict:
    if not legs:
        raise ValueError("腿列表为空")

    underlying = legs[0]["underlying"]
    expiry = legs[0]["expiry"]
    for leg in legs[1:]:
        if leg.get("underlying") != underlying or leg.get("expiry") != expiry:
            raise ValueError(
                "仅支持同标的、同到期日的组合(日历价差/跨标的组合暂不支持)。"
                f"腿 {leg.get('underlying')} {leg.get('expiry')} 与首腿 {underlying} {expiry} 不一致"
            )
    price = (
        underlying_price
        if (underlying_price is not None and math.isfinite(underlying_price) and underlying_price > 0)
        else get_underlying_price(underlying)
    )
    if not price:
        raise ValueError(f"无法获取 {underlying} 现价")

    # 各腿成本/收入:成交价 last → 腿内 price → chain IV 的 BS 估算(见 _resolve_leg_price)
    if chain is None:
        chain = get_option_chain(underlying, expiry)
    sign_map = {"BUY": 1, "SELL": -1}

    leg_costs = []
    raw_costs = []
    payoff_legs = []
    for leg in legs:
        strike = float(leg["strike"])
        ot = str(leg["type"]).upper()
        is_stock = ot in ("STOCK", "SHARE", "UNDERLYING")
        cp = "C" if ot in ("CALL", "C") else "P"
        action = leg.get("action", "BUY").upper()
        qty = float(leg.get("quantity", 1))
        sign = sign_map[action]
        if not math.isfinite(qty) or qty <= 0:
            raise ValueError("组合腿数量必须为有限正数")
        if not is_stock and (ot not in ("CALL", "C", "PUT", "P")
                             or not math.isfinite(strike) or strike <= 0):
            raise ValueError("期权腿需要有效的类型和行权价")
        payoff_legs.append((strike, "STOCK" if is_stock else cp, sign * qty * 100))

        if is_stock:
            # 正股腿:成本与到期价值都直接用正股价(每手 100 股)
            last = price
            cost = last * sign * qty * 100
            raw_costs.append(cost)
            leg_costs.append({"leg": f"{action} {qty}× 正股 @{last:.2f}",
                              "last": last, "cost": round(cost, 2), "price_source": "last"})
            continue

        last_key = "call_last" if cp == "C" else "put_last"
        iv_key = "call_iv" if cp == "C" else "put_iv"
        row = next((r for r in chain
                    if r.get("standard") is not False
                    and to_float(r.get("strike")) is not None
                    and abs(to_float(r.get("strike")) - strike) < 0.001), None)
        last, source = _resolve_leg_price(row, last_key, iv_key, leg, price, strike, cp,
                                          expiry, rate)
        cost = last * sign * qty * 100  # 美股期权每张 100 股
        raw_costs.append(cost)
        tag = {"manual": "(手动指定价)", "bs_from_iv": "(BS估算,当日无成交)"}.get(source, "")
        leg_costs.append({"leg": f"{action} {qty}× {strike} {leg['type']}{tag}",
                          "last": last, "cost": round(cost, 2), "price_source": source})

    total_cost = math.fsum(raw_costs)

    def payoff(settlement: float) -> float:
        return math.fsum(
            weight * (settlement if cp == "STOCK" else _intrinsic(settlement, strike, cp))
            for strike, cp, weight in payoff_legs
        ) - total_cost

    # 到期损益在行权价之间为线性函数，最右区间由正股和 Call 的净头寸决定。
    knots = sorted({0.0} | {strike for strike, cp, _ in payoff_legs if cp != "STOCK"})
    values = [payoff(knot) for knot in knots]
    tail_slope = math.fsum(weight for _, cp, weight in payoff_legs if cp in ("C", "STOCK"))
    tolerance = 1e-9
    roots = {k for k, v in zip(knots, values) if abs(v) <= tolerance}
    flat_ranges = []
    for a, b, va, vb in zip(knots, knots[1:], values, values[1:]):
        if abs(va) <= tolerance and abs(vb) <= tolerance:
            flat_ranges.append([a, b])
        elif (va < -tolerance and vb > tolerance) or (va > tolerance and vb < -tolerance):
            roots.add(a - va * (b - a) / (vb - va))
    if tail_slope and values[-1] * tail_slope < 0 and abs(values[-1]) > tolerance:
        roots.add(knots[-1] - values[-1] / tail_slope)
    elif not tail_slope and abs(values[-1]) <= tolerance:
        flat_ranges.append([knots[-1], None])

    is_profit_capped = tail_slope <= 0
    is_loss_capped = tail_slope >= 0
    max_profit = max(values)
    max_loss = min(values)
    break_evens = sorted({round(root, 2) for root in roots})
    curve = [{"price": round(price * (.7 + .6 * i / 400), 2),
              "pnl": round(payoff(price * (.7 + .6 * i / 400)), 2)}
             for i in range(401)]

    result = {
        "underlying": underlying,
        "expiry": expiry,
        "underlying_price": price,
        "underlying_price_source": get_underlying_price_info(underlying),
        "cost_basis": ("各腿成本价: chain 的 last;last 无成交时依次用腿内 price(手动指定)、"
                       "chain IV 的 BS 估算,见 legs_detail.price_source"),
        "estimated_legs": sum(1 for lc in leg_costs if lc["price_source"] != "last"),
        "total_cost": round(total_cost, 2),
        "cost_per_share": round(total_cost / 100, 4),
        "net_credit": total_cost < 0,  # 净收入(卖方策略)
        "break_even_points": break_evens,
        "break_even_ranges": flat_ranges,
        "max_profit": f"{round(max_profit, 2)} (有限)" if is_profit_capped else "未封顶",
        "max_loss": f"{round(max_loss, 2)} (有限)" if is_loss_capped else "未封顶",
        "legs_detail": leg_costs,
        "curve_points": len(curve),
        "note": "到期损益(基于各腿 last price 估算成本,不含时间价值/组合摆盘价;"
                "最大盈亏覆盖所有非负结算价。last=0(当日无成交)不算免费期权:"
                "依次改用腿内 price 或 BS 估算,见 legs_detail.price_source)",
    }

    if output_json:
        print_json(result)
        return result
    if quiet:
        return result

    print(f"组合损益分析({len(legs)} 腿,到期 {expiry})")
    print(f"  正股现价: {price}{price_source_note(underlying)}")
    print(f"  净成本:   ${total_cost} ({'净支出' if total_cost > 0 else '净收入'})")
    print(f"  盈亏平衡: {break_evens}")
    if flat_ranges:
        print(f"  盈亏平衡区间: {flat_ranges}")
    print(f"  最大盈利: {result['max_profit']}")
    print(f"  最大亏损: {result['max_loss']}")
    if result["estimated_legs"]:
        print(f"  ⚠️ {result['estimated_legs']} 腿无当日成交价(不是免费期权),成本为估算值,"
              f"损益数字仅供参考")
    print(f"  各腿: ")
    for lc in leg_costs:
        print(f"    {lc['leg']}  价={lc['last']}  成本={lc['cost']}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="期权组合到期损益分析")
    parser.add_argument("legs", help="腿列表:JSON 字符串或 .json 文件路径")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    parser.add_argument("--rate", type=float, default=0.045,
                        help="无风险利率(年化,默认 0.045),仅用于 last=0 时的 BS 估算")
    args = parser.parse_args()
    try:
        legs = _load_legs(args.legs)
        analyze_pnl(legs, output_json=args.output_json, rate=args.rate)
    except Exception as e:
        print_error("损益分析", str(e))
        sys.exit(1)
