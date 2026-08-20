"""找出 Put Wall / Call Wall(最大持仓/成交的行权价 = 关键支撑/阻力)。

口径(自动选择):
  ✅ 优先 **真实 OI**(calc-index 按合约查询):持仓量最大的行权价,
     与主流 Wall 分析一致(存量仓位)
  ⬇️ OI 不可用时回退 **当日成交量代理**(chain 的 call_vol/put_vol)

理论依据:
  - Put Wall: 大量 Put 持押在该价位,做市商做多 delta 对冲 → 价格跌至此处有买盘
  - Call Wall: 大量 Call 持押在该价位,做市商做空 delta 对冲 → 价格涨至此处有卖压
  - 当价格穿越 Wall 时,对冲方向反转,可能加速突破(磁吸效应)

用法:
    python get_put_call_wall.py MSFT.US --date 2026-09-18
    python get_put_call_wall.py MSFT.US --date 2026-09-18 --walls 3  # 显示 top3
    python get_put_call_wall.py MSFT.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    find_atm_strike,
    get_chain_oi,
    get_option_chain,
    get_underlying_price,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def find_walls(chain: list[dict], oi_data: dict | None, n: int = 3,
               price: float | None = None) -> dict:
    """从 OI(优先)或成交量中找 Put/Call Wall(top n 行权价)。

    约定:Call Wall 只在 ≥现价 的行权价中找(上方阻力),Put Wall 只在 ≤现价
    的行权价中找(下方支撑)——深度价内的大持仓是存量头寸,不构成该侧的墙。
    某侧无数据时放宽到全部行权价。

    Returns:
        {put_walls:[{strike, weight, iv}], call_walls:[...], mode: 'oi'|'volume'}
    """
    put_rows, call_rows = [], []
    mode = "volume"
    if oi_data and oi_data.get("oi_mode"):
        mode = "oi"
        for s, v in sorted(oi_data["strikes"].items()):
            if v["put_oi"] > 0:
                put_rows.append({"strike": s, "weight": float(v["put_oi"]), "iv": v["put_iv"]})
            if v["call_oi"] > 0:
                call_rows.append({"strike": s, "weight": float(v["call_oi"]), "iv": v["call_iv"]})
    if not put_rows and not call_rows:
        for r in chain:
            strike = to_float(r.get("strike"))
            put_vol = to_float(r.get("put_vol"), 0) or 0
            call_vol = to_float(r.get("call_vol"), 0) or 0
            put_iv = to_float(r.get("put_iv"))
            call_iv = to_float(r.get("call_iv"))
            if strike is not None:
                if put_vol > 0:
                    put_rows.append({"strike": strike, "weight": put_vol, "iv": put_iv})
                if call_vol > 0:
                    call_rows.append({"strike": strike, "weight": call_vol, "iv": call_iv})

    if price:
        put_otm = [r for r in put_rows if r["strike"] <= price]
        call_otm = [r for r in call_rows if r["strike"] >= price]
        put_rows = put_otm or put_rows
        call_rows = call_otm or call_rows

    put_rows.sort(key=lambda x: x["weight"], reverse=True)
    call_rows.sort(key=lambda x: x["weight"], reverse=True)
    return {"put_walls": put_rows[:n], "call_walls": call_rows[:n], "mode": mode}


def _wall_label(strike: float, price: float) -> str:
    """判断 Wall 相对现价的位置。"""
    if strike < price:
        pct = (price - strike) / price * 100
        return f"支撑(现价下方 {pct:.1f}%)"
    if strike > price:
        pct = (strike - price) / price * 100
        return f"阻力(现价上方 {pct:.1f}%)"
    return "ATM(现价附近)"


def analyze_walls(
    symbol: str,
    date: str,
    walls: int = 3,
    output_json: bool = False,
) -> dict:
    price = get_underlying_price(symbol)
    if not price:
        raise ValueError(f"无法获取 {symbol} 现价")
    chain = get_option_chain(symbol, date)
    if is_empty(chain):
        raise ValueError(f"{symbol} 在 {date} 无期权链数据")

    atm = find_atm_strike(chain, price)
    oi_data = get_chain_oi(symbol, date)
    result_walls = find_walls(chain, oi_data, n=walls, price=price)
    mode = result_walls["mode"]

    for w in result_walls["put_walls"]:
        w["position"] = _wall_label(w["strike"], price)
    for w in result_walls["call_walls"]:
        w["position"] = _wall_label(w["strike"], price)

    put_wall_top = result_walls["put_walls"][0]["strike"] if result_walls["put_walls"] else None
    call_wall_top = result_walls["call_walls"][0]["strike"] if result_walls["call_walls"] else None

    weight_name = "OI" if mode == "oi" else "成交量(近似)"
    result = {
        "symbol": symbol,
        "expiry": date,
        "underlying_price": price,
        "atm_strike": atm,
        "weight_mode": mode,
        "primary_put_wall": put_wall_top,
        "primary_call_wall": call_wall_top,
        "walls": result_walls,
        "note": (f"基于真实 OI(存量持仓口径)" if mode == "oi"
                 else "基于当日成交量(近似,Longbridge chain 无按行权价 OI,已回退)"),
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} Put/Call Wall 分析(到期 {date},现价 {price})")
    print(f"  口径: {'✅ 真实 OI' if mode == 'oi' else '⚠️ 成交量近似'}")
    print(f"  ATM 行权价: {atm}")
    print()
    print(f"🟢 Put Wall(最大持仓 Put,关键支撑):")
    if result_walls["put_walls"]:
        print_display_table(
            [{"行权价": w["strike"], weight_name: f"{w['weight']:,.0f}",
              "IV": f"{w['iv']*100:.1f}%" if w["iv"] else "",
              "位置": w["position"]} for w in result_walls["put_walls"]],
            columns=["行权价", weight_name, "IV", "位置"])
    print()
    print(f"🔴 Call Wall(最大持仓 Call,关键阻力):")
    if result_walls["call_walls"]:
        print_display_table(
            [{"行权价": w["strike"], weight_name: f"{w['weight']:,.0f}",
              "IV": f"{w['iv']*100:.1f}%" if w["iv"] else "",
              "位置": w["position"]} for w in result_walls["call_walls"]],
            columns=["行权价", weight_name, "IV", "位置"])
    print()
    if put_wall_top and call_wall_top:
        print(f"预计区间: {put_wall_top}(支撑) ~ {call_wall_top}(阻力)")
        if put_wall_top < price < call_wall_top:
            print(f"  现价 {price} 在区间内,Wall 形成箱体震荡")
        elif price <= put_wall_top:
            print(f"  ⚠️ 现价已跌破 Put Wall {put_wall_top},可能向下突破")
        else:
            print(f"  ⚠️ 现价已突破 Call Wall {call_wall_top},可能向上突破")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Put/Call Wall 分析(真实 OI 优先)")
    parser.add_argument("symbol", help="正股代码,如 MSFT.US")
    parser.add_argument("--date", required=True, help="到期日 YYYY-MM-DD")
    parser.add_argument("--walls", type=int, default=3, help="显示 top N 个 Wall(默认 3)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze_walls(args.symbol, args.date, walls=args.walls, output_json=args.output_json)
    except Exception as e:
        print_error("Put/Call Wall 分析", str(e))
        sys.exit(1)
