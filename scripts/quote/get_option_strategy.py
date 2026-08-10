"""生成标准期权策略组合腿(B 档·计算)。

对应 Futu: get_option_strategy(策略组合腿列表)

根据策略类型 + 标的现价,自动选择行权价并生成组合腿。生成的腿可作为
calc_option_greeks.py / calc_option_pnl.py 的输入。

支持策略:
  STRADDLE      买 ATM Call + ATM Put(同一行权价)
  STRANGLE      买 OTM Call + OTM Put(不同行权价)
  BULL_CALL_SPREAD  买 ATM Call + 卖 OTM Call
  BEAR_PUT_SPREAD   买 ATM Put + 卖 OTM Put
  BUTTERFLY     买 ITM Call + 卖 2 ATM Call + 买 OTM Call
  COLLAR        买正股 + 买 OTM Put + 卖 OTM Call
  COVERED_CALL  买正股 + 卖 OTM Call
  CASH_SECURED_PUT 卖 OTM Put

用法:
    python get_option_strategy.py AAPL.US 2026-08-14 STRADDLE
    python get_option_strategy.py AAPL.US 2026-08-14 BULL_CALL_SPREAD --otm-pct 0.05
    python get_option_strategy.py AAPL.US 2026-08-14 STRANGLE --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    find_atm_strike,
    get_option_chain,
    get_underlying_price,
    print_error,
    print_json,
    to_float,
)


def _nearest_strike(chain: list[dict], target: float) -> float | None:
    """从 chain 找最接近 target 的行权价。"""
    best, best_diff = None, float("inf")
    for r in chain:
        s = to_float(r.get("strike"))
        if s is not None and abs(s - target) < best_diff:
            best_diff, best = abs(s - target), s
    return best


def build_strategy(
    underlying: str,
    expiry: str,
    strategy: str,
    otm_pct: float = 0.05,
    output_json: bool = False,
) -> dict:
    price = get_underlying_price(underlying)
    if not price:
        raise ValueError(f"无法获取 {underlying} 现价")
    chain = get_option_chain(underlying, expiry)
    if not chain:
        raise ValueError(f"{underlying} 在 {expiry} 无期权链")

    atm = find_atm_strike(chain, price)
    strikes_sorted = sorted([to_float(r["strike"]) for r in chain if to_float(r.get("strike")) is not None])
    # OTM Call = 现价×(1+otm_pct), OTM Put = 现价×(1-otm_pct)
    otm_call_target = price * (1 + otm_pct)
    otm_put_target = price * (1 - otm_pct)
    otm_call = _nearest_strike(chain, otm_call_target)
    otm_put = _nearest_strike(chain, otm_put_target)
    # ITM Call = 现价×(1-otm_pct)
    itm_call = _nearest_strike(chain, otm_put_target)

    strat = strategy.upper()
    legs: list[dict] = []

    def leg(strike, otype, action, qty=1):
        return {"underlying": underlying, "expiry": expiry, "strike": strike,
                "type": otype, "action": action, "quantity": qty}

    if strat == "STRADDLE":
        legs = [leg(atm, "CALL", "BUY"), leg(atm, "PUT", "BUY")]
    elif strat == "STRANGLE":
        legs = [leg(otm_call, "CALL", "BUY"), leg(otm_put, "PUT", "BUY")]
    elif strat == "BULL_CALL_SPREAD":
        legs = [leg(atm, "CALL", "BUY"), leg(otm_call, "CALL", "SELL")]
    elif strat == "BEAR_PUT_SPREAD":
        legs = [leg(atm, "PUT", "BUY"), leg(otm_put, "PUT", "SELL")]
    elif strat == "BUTTERFLY":
        legs = [leg(itm_call, "CALL", "BUY"), leg(atm, "CALL", "SELL", 2), leg(otm_call, "CALL", "BUY")]
    elif strat == "COLLAR":
        legs = [leg(price, "STOCK", "BUY"), leg(otm_put, "PUT", "BUY"), leg(otm_call, "CALL", "SELL")]
    elif strat == "COVERED_CALL":
        legs = [leg(price, "STOCK", "BUY"), leg(otm_call, "CALL", "SELL")]
    elif strat == "CASH_SECURED_PUT":
        legs = [leg(otm_put, "PUT", "SELL")]
    else:
        raise ValueError(
            f"不支持的策略 {strategy}。支持: STRADDLE/STRANGLE/BULL_CALL_SPREAD/"
            "BEAR_PUT_SPREAD/BUTTERFLY/COLLAR/COVERED_CALL/CASH_SECURED_PUT"
        )

    result = {
        "strategy": strat,
        "underlying": underlying,
        "expiry": expiry,
        "underlying_price": price,
        "atm_strike": atm,
        "otm_call_strike": otm_call,
        "otm_put_strike": otm_put,
        "otm_pct": otm_pct,
        "legs": legs,
        "description": _describe(strat),
        "next_step": "把 legs 传给 calc_option_greeks.py 或 calc_option_pnl.py 分析",
    }

    if output_json:
        print_json(result)
        return result

    print(f"策略: {strat}  标的 {underlying}(现价 {price})  到期 {expiry}")
    print(f"  ATM={atm}  OTM Call={otm_call}  OTM Put={otm_put}")
    print(f"  {_describe(strat)}")
    print(f"  组合腿:")
    for lg in legs:
        print(f"    {lg['action']} {lg['quantity']}× {lg['strike']} {lg['type']}")
    print(f"\n  把以下 JSON 传给 calc_option_pnl.py / calc_option_greeks.py:")
    print(json.dumps(legs, ensure_ascii=False))
    return result


def _describe(s: str) -> str:
    return {
        "STRADDLE": "买入同行权价 Call+Put,赌大波动(不计方向)",
        "STRANGLE": "买 OTM Call+Put,成本更低但需更大波动",
        "BULL_CALL_SPREAD": "买 ATM Call 卖 OTM Call,温和看多,成本降低",
        "BEAR_PUT_SPREAD": "买 ATM Put 卖 OTM Put,温和看空",
        "BUTTERFLY": "买 ITM+OTM Call 卖 2 ATM Call,赌价格稳定在 ATM",
        "COLLAR": "持股+买 Put+卖 Call,锁定下行牺牲上行",
        "COVERED_CALL": "持股+卖 OTM Call,收租降低成本",
        "CASH_SECURED_PUT": "卖 OTM Put,等跌到行权价接货",
    }.get(s, s)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成标准期权策略组合腿")
    parser.add_argument("underlying", help="正股代码")
    parser.add_argument("expiry", help="到期日 YYYY-MM-DD")
    parser.add_argument("strategy", help="策略类型(见 --help 上方说明)")
    parser.add_argument("--otm-pct", type=float, default=0.05, help="OTM 距离比例(默认 0.05=5%%)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        build_strategy(args.underlying, args.expiry, args.strategy,
                       otm_pct=args.otm_pct, output_json=args.output_json)
    except Exception as e:
        print_error("策略生成", str(e))
        sys.exit(1)
