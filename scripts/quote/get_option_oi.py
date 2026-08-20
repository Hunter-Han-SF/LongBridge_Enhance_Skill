"""按行权价的未平仓量(OI)+ P/C OI 比率 + OI 墙(原生数据)。

数据源: longbridge calc-index 按合约批量查询(实测可一次多合约,静默跳过无数据合约)。
这是 chain 之外唯一的按行权价 OI 数据源:
  - P/C OI 比率(存量仓位口径,比成交量口径更反映真实持仓倾向)
  - OI 墙 = OI 最大的行权价(比成交量代理更接近真实支撑/阻力)
  - 原生 delta/gamma(服务端计算,非 BS 近似)

⚠️ 逐合约查询有限频成本:默认只查现价 ±25%、离 ATM 最近的 60 档(约 12 次 CLI 调用)。

用法:
    python get_option_oi.py MSFT.US                        # 最近到期日
    python get_option_oi.py MSFT.US --date 2026-09-18     # 指定到期日
    python get_option_oi.py MSFT.US --range 0.15 --max-strikes 40 --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_chain_oi,
    get_option_expirations,
    get_underlying_price,
    print_display_table,
    print_error,
    print_json,
)


def analyze(symbol: str, date: str | None = None, near_atm_pct: float = 0.25,
            max_strikes: int = 60, output_json: bool = False) -> dict:
    price = get_underlying_price(symbol)
    if not price:
        raise ValueError(f"无法获取 {symbol} 现价")
    if date is None:
        exps = get_option_expirations(symbol)
        if not exps:
            raise ValueError(f"{symbol} 无可用到期日(仅美股支持)")
        date = exps[0]

    data = get_chain_oi(symbol, date, near_atm_pct=near_atm_pct, max_strikes=max_strikes)
    if not data.get("oi_mode"):
        raise ValueError("无 OI 数据(calc-index 未返回任何未平仓量,可能非美股或权限不足)")

    strikes = data["strikes"]
    rows = []
    for s in sorted(strikes):
        v = strikes[s]
        rows.append({
            "strike": s,
            "call_oi": v["call_oi"],
            "put_oi": v["put_oi"],
            "total_oi": v["call_oi"] + v["put_oi"],
            "put_heavy": round(v["put_oi"] / (v["call_oi"] + v["put_oi"]), 2)
                         if (v["call_oi"] + v["put_oi"]) else None,
            "call_delta": v["call_delta"],
            "put_delta": v["put_delta"],
        })

    # OI 墙(持仓量最大的行权价)
    put_wall = max(rows, key=lambda r: r["put_oi"]) if rows else None
    call_wall = max(rows, key=lambda r: r["call_oi"]) if rows else None
    pc = data.get("pc_oi_ratio")

    if pc is None:
        pc_label = "N/A"
    elif pc > 1.0:
        pc_label = "偏空(put 持仓占优)"
    elif pc < 0.6:
        pc_label = "偏多(call 持仓占优)"
    else:
        pc_label = "中性"

    result = {
        "symbol": symbol,
        "expiry": date,
        "underlying_price": price,
        "strikes_queried": data["strikes_queried"],
        "total_call_oi": data["total_call_oi"],
        "total_put_oi": data["total_put_oi"],
        "pc_oi_ratio": pc,
        "pc_oi_label": pc_label,
        "put_oi_wall": {"strike": put_wall["strike"], "oi": put_wall["put_oi"]} if put_wall else None,
        "call_oi_wall": {"strike": call_wall["strike"], "oi": call_wall["call_oi"]} if call_wall else None,
        "oi_table": rows,
        "note": "OI 为存量持仓口径(与成交量口径的 P/C 比率含义不同:持仓=倾向,成交=情绪)。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 期权 OI 分布(到期 {date},现价 {price},查询 {data['strikes_queried']} 档)")
    print(f"  Call OI 合计: {data['total_call_oi']:,}   Put OI 合计: {data['total_put_oi']:,}"
          f"   P/C OI 比率: {pc} → {pc_label}")
    if put_wall:
        print(f"  🟢 Put OI 墙: {put_wall['strike']}(持仓 {put_wall['put_oi']:,},下方支撑)")
    if call_wall:
        print(f"  🔴 Call OI 墙: {call_wall['strike']}(持仓 {call_wall['call_oi']:,},上方阻力)")
    print()
    # 只显示 OI 最大的前 15 档
    top = sorted(rows, key=lambda r: r["total_oi"], reverse=True)[:15]
    top.sort(key=lambda r: r["strike"])
    print("OI 集中档(top 15 by total OI):")
    print_display_table(
        [{"行权价": r["strike"], "Call OI": f"{r['call_oi']:,}", "Put OI": f"{r['put_oi']:,}",
          "Put 占比": r["put_heavy"]} for r in top],
        columns=["行权价", "Call OI", "Put OI", "Put 占比"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="按行权价 OI + P/C OI 比率 + OI 墙(原生)")
    parser.add_argument("symbol", help="正股代码,如 MSFT.US")
    parser.add_argument("--date", default=None, help="到期日 YYYY-MM-DD(默认最近)")
    parser.add_argument("--range", type=float, default=0.25, dest="near_atm_pct",
                        help="查询范围 ±比例(默认 0.25)")
    parser.add_argument("--max-strikes", type=int, default=60, dest="max_strikes",
                        help="最多查询行权价数(默认 60,控制限频)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, date=args.date, near_atm_pct=args.near_atm_pct,
                max_strikes=args.max_strikes, output_json=args.output_json)
    except Exception as e:
        print_error("期权 OI", str(e))
        sys.exit(1)
