"""隐含波动幅度(Expected Move,ATM Straddle 法)。

跨式成本幅度 = ATM 跨式权利金 / 现价，历史字段 expected_move_pct 使用该口径。
跨式到期盈亏平衡 = 行权价 ± 权利金。
IV 标准差尺度 = ATM IV × √T，以现价为中心展示。

用法:
    python calc_expected_move.py AAPL.US                    # 最近到期日
    python calc_expected_move.py AAPL.US --date 2026-09-18  # 指定到期日
    python calc_expected_move.py AAPL.US --all              # 全部到期日一览
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    days_to_years,
    find_atm_strike,
    get_atm_iv,
    get_option_chain,
    get_option_expirations,
    get_underlying_price,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _straddle_cost(chain: list[dict], strike: float) -> float | None:
    for r in chain:
        s = to_float(r.get("strike"))
        if s is not None and abs(s - strike) < 0.001:
            c = to_float(r.get("call_last"))
            p = to_float(r.get("put_last"))
            if c is not None and p is not None:
                return c + p
    return None


def _one_expiry(symbol: str, price: float, expiry: str) -> dict | None:
    chain = get_option_chain(symbol, expiry)
    if is_empty(chain):
        return None
    atm = find_atm_strike(chain, price)
    if atm is None:
        return None
    straddle = _straddle_cost(chain, atm)
    if not straddle:
        return None
    T = days_to_years(expiry)
    if T <= 0:
        return None
    iv = get_atm_iv(chain, price)
    em_pct = straddle / price * 100
    # 理论对照:ATM straddle ≈ 0.8·S·σ·√T(近似),此处直接用 IV×√T
    em_iv_pct = (iv * math.sqrt(T) * 100) if (iv and T > 0) else None
    lo, hi = price * (1 - em_pct / 100), price * (1 + em_pct / 100)
    return {
        "expiry": expiry, "days": round(T * 365), "atm_strike": atm,
        "straddle_cost": round(straddle, 2),
        "expected_move_pct": round(em_pct, 2),
        "range_low": round(lo, 2), "range_high": round(hi, 2),
        "iv_implied_move_pct": round(em_iv_pct, 2) if em_iv_pct else None,
        "straddle_break_even_low": round(atm - straddle, 2),
        "straddle_break_even_high": round(atm + straddle, 2),
        "iv_range_low": round(price * (1 - em_iv_pct / 100), 2) if em_iv_pct else None,
        "iv_range_high": round(price * (1 + em_iv_pct / 100), 2) if em_iv_pct else None,
        "iv_atm": iv,
    }


def analyze(symbol: str, date: str | None = None, show_all: bool = False,
            output_json: bool = False) -> dict:
    price = get_underlying_price(symbol)
    if not price:
        raise ValueError(f"无法获取 {symbol} 现价")

    if show_all or date is None:
        expirations = get_option_expirations(symbol)
        if not expirations:
            raise ValueError(f"{symbol} 无可用到期日(非美股或无期权)")
        targets = expirations[:8] if show_all else [date] if date else [expirations[0]]
    else:
        targets = [date]

    rows = []
    for exp in targets:
        r = _one_expiry(symbol, price, exp)
        if r:
            rows.append(r)

    if not rows:
        raise ValueError("无有效 ATM straddle 数据(chain 缺少 ATM 报价)")

    result = {
        "symbol": symbol,
        "underlying_price": price,
        "expected_moves": rows,
        "main": rows[0],
        "note": "跨式成本幅度以现价为中心展示。跨式盈亏平衡价按行权价计算，IV 标准差尺度单独列示。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 隐含波动幅度(现价 {price})")
    print()
    print_display_table(
        [{"到期日": r["expiry"], "剩余天数": r["days"], "ATM": r["atm_strike"],
          "Straddle": r["straddle_cost"], "跨式成本幅度": f"±{r['expected_move_pct']}%",
          "跨式成本区间": f"{r['range_low']} ~ {r['range_high']}"} for r in rows],
        columns=["到期日", "剩余天数", "ATM", "Straddle", "跨式成本幅度", "跨式成本区间"])
    m = result["main"]
    print()
    print(f"  主参考(最近到期 {m['expiry']}): 跨式成本幅度 ±{m['expected_move_pct']}%"
          f"({m['range_low']} ~ {m['range_high']})")
    print(f"  跨式到期盈亏平衡价: {m['straddle_break_even_low']} ~ {m['straddle_break_even_high']}")
    if m.get("iv_implied_move_pct"):
        print(f"  IV 标准差尺度 ±{m['iv_implied_move_pct']}% ({m['iv_range_low']} ~ {m['iv_range_high']})")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="隐含波动幅度(ATM Straddle 法)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--date", default=None, help="到期日 YYYY-MM-DD(默认最近)")
    parser.add_argument("--all", action="store_true", help="列出全部近期到期日")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, date=args.date, show_all=args.all, output_json=args.output_json)
    except Exception as e:
        print_error("隐含波动幅度", str(e))
        sys.exit(1)
