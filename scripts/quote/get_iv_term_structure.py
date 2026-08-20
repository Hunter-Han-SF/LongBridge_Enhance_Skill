"""IV 期限结构(各到期日 ATM IV 连线)。

期限结构反映市场对不同时间窗口的波动预期:
  Contango(近低远高): 正常状态,事件(财报)不确定性集中在远月 → 适合卖近买远日历价差
  Backwardation(近高远低): 近期事件驱动(财报/FOMC 在即),近月 IV 含事件溢价
                          → 财报后近月 IV 会塌陷(IV Crush)

指标:
  - 各到期日 ATM IV(取 call/put 均值)
  - 近远月斜率 = 远月IV - 近月IV(负 = 近月溢价,事件临近)
  - 检测"事件溢价"到期日(某到期日 IV 显著高于前后)

用法:
    python get_iv_term_structure.py AAPL.US
    python get_iv_term_structure.py AAPL.US --count 8 --json
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
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def analyze(symbol: str, count: int = 8, output_json: bool = False) -> dict:
    price = get_underlying_price(symbol)
    if not price:
        raise ValueError(f"无法获取 {symbol} 现价")
    expirations = get_option_expirations(symbol)[:count]
    if not expirations:
        raise ValueError(f"{symbol} 无可用到期日")

    rows = []
    for exp in expirations:
        chain = get_option_chain(symbol, exp)
        if not chain:
            continue
        atm = find_atm_strike(chain, price)
        if atm is None:
            continue
        civ = piv = None
        for r in chain:
            s = to_float(r.get("strike"))
            if s is not None and abs(s - atm) < 0.001:
                civ = to_float(r.get("call_iv"))
                piv = to_float(r.get("put_iv"))
                break
        vals = [v for v in (civ, piv) if v and v > 0]
        if not vals:
            continue
        rows.append({"expiry": exp, "days": None, "atm_strike": atm,
                     "call_iv_pct": round((civ or 0) * 100, 2) if civ else None,
                     "put_iv_pct": round((piv or 0) * 100, 2) if piv else None,
                     "atm_iv_pct": round(sum(vals) / len(vals) * 100, 2)})

    if len(rows) < 2:
        raise ValueError("有效到期日不足 2 个,无法画期限结构")

    # 天数(相对第一个到期日逐个算自然日差)
    from datetime import datetime
    today = datetime.now()
    for r in rows:
        try:
            d = (datetime.strptime(r["expiry"], "%Y-%m-%d") - today).days
            r["days"] = max(d, 0)
        except ValueError:
            r["days"] = None

    slope = rows[-1]["atm_iv_pct"] - rows[0]["atm_iv_pct"]
    shape = ("Backwardation(近月溢价,近期事件驱动,警惕 IV Crush)" if slope < -1 else
             "Contango(远月更高,正常期限结构)" if slope > 1 else "平坦")

    # 事件溢价检测:某中期到期日 IV 比前后邻点都高出 2pp 以上
    event_expiry = None
    for i in range(1, len(rows) - 1):
        if (rows[i]["atm_iv_pct"] > rows[i - 1]["atm_iv_pct"] + 2
                and rows[i]["atm_iv_pct"] > rows[i + 1]["atm_iv_pct"] + 2):
            event_expiry = rows[i]["expiry"]
            break

    result = {
        "symbol": symbol,
        "underlying_price": price,
        "term_structure": rows,
        "slope_pp": round(slope, 2),
        "shape": shape,
        "event_premium_expiry": event_expiry,
        "note": "ATM IV 取 call/put 均值。事件溢价=某到期日显著高于邻点(财报/CPI 等落在该周)。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} IV 期限结构(现价 {price})")
    print_display_table(
        [{"到期日": r["expiry"], "剩余天数": r["days"], "ATM": r["atm_strike"],
          "Call IV": r["call_iv_pct"], "Put IV": r["put_iv_pct"], "ATM IV": r["atm_iv_pct"]}
         for r in rows],
        columns=["到期日", "剩余天数", "ATM", "Call IV", "Put IV", "ATM IV"])
    print()
    print(f"  近远月斜率: {slope:+.2f}pp → {shape}")
    if event_expiry:
        print(f"  ⚠️ {event_expiry} 存在事件溢价(IV 显著高于邻点,可能对应财报/宏观数据周)")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IV 期限结构(各到期日 ATM IV)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--count", type=int, default=8, help="到期日数量(默认 8)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("IV 期限结构", str(e))
        sys.exit(1)
