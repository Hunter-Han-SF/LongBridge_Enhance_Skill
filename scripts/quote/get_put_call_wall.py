"""找出 Put Wall / Call Wall(最大成交量的行权价 = 关键支撑/阻力)。

⚠️ 重要限制:Longbridge 的 option chain 不返回按行权价分布的未平仓量(OI),
   只有当日成交量(call_vol/put_vol)。本脚本用成交量作为 OI 的代理:
   - 成交量最大的 Put 行权价 = Put Wall(支撑位,跌破会放大下跌)
   - 成交量最大的 Call 行权价 = Call Wall(阻力位,突破会放大上涨)
   这是对真实 OI Wall 的近似,流动性好的标的近似度较高。

理论依据:
  - Put Wall: 大量 Put 在该价位成交,做市商做多 delta 对冲 → 价格跌至此处有买盘
  - Call Wall: 大量 Call 在该价位成交,做市商做空 delta 对冲 → 价格涨至此处有卖压
  - 当价格穿越 Wall 时,对冲方向反转,可能加速突破(磁吸效应)

用法:
    python get_put_call_wall.py AAPL.US --date 2026-09-18
    python get_put_call_wall.py AAPL.US --date 2026-09-18 --walls 3  # 显示 top3
    python get_put_call_wall.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    find_atm_strike,
    get_option_chain,
    get_underlying_price,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def find_walls(chain: list[dict], n: int = 3) -> dict:
    """从 chain 找 Put/Call Wall(按成交量排序的 top n 行权价)。

    Returns:
        {put_walls:[{strike, vol, iv}], call_walls:[{strike, vol, iv}]}
    """
    put_rows = []
    call_rows = []
    for r in chain:
        strike = to_float(r.get("strike"))
        put_vol = to_float(r.get("put_vol"), 0) or 0
        call_vol = to_float(r.get("call_vol"), 0) or 0
        put_iv = to_float(r.get("put_iv"))
        call_iv = to_float(r.get("call_iv"))
        if strike is not None:
            if put_vol > 0:
                put_rows.append({"strike": strike, "vol": put_vol, "iv": put_iv})
            if call_vol > 0:
                call_rows.append({"strike": strike, "vol": call_vol, "iv": call_iv})

    # 按成交量降序
    put_rows.sort(key=lambda x: x["vol"], reverse=True)
    call_rows.sort(key=lambda x: x["vol"], reverse=True)

    return {
        "put_walls": put_rows[:n],
        "call_walls": call_rows[:n],
    }


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
    result_walls = find_walls(chain, n=walls)

    # 加位置标签
    for w in result_walls["put_walls"]:
        w["position"] = _wall_label(w["strike"], price)
    for w in result_walls["call_walls"]:
        w["position"] = _wall_label(w["strike"], price)

    # 区间判断
    put_wall_top = result_walls["put_walls"][0]["strike"] if result_walls["put_walls"] else None
    call_wall_top = result_walls["call_walls"][0]["strike"] if result_walls["call_walls"] else None

    result = {
        "symbol": symbol,
        "expiry": date,
        "underlying_price": price,
        "atm_strike": atm,
        "primary_put_wall": put_wall_top,
        "primary_call_wall": call_wall_top,
        "walls": result_walls,
        "note": "基于当日成交量(非真实 OI)。Longbridge chain 不返回按行权价的 OI,"
                "用成交量作为代理,流动性好的标的近似度较高。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} Put/Call Wall 分析(到期 {date},现价 {price})")
    print(f"  ⚠️ 基于成交量近似(非真实 OI),见 note")
    print(f"  ATM 行权价: {atm}")
    print()
    print(f"🟢 Put Wall(最大成交 Put,关键支撑):")
    if result_walls["put_walls"]:
        print_display_table(
            [{"行权价": w["strike"], "成交量": w["vol"], "IV": f"{w['iv']*100:.1f}%" if w["iv"] else "",
              "位置": w["position"]} for w in result_walls["put_walls"]],
            columns=["行权价", "成交量", "IV", "位置"])
    print()
    print(f"🔴 Call Wall(最大成交 Call,关键阻力):")
    if result_walls["call_walls"]:
        print_display_table(
            [{"行权价": w["strike"], "成交量": w["vol"], "IV": f"{w['iv']*100:.1f}%" if w["iv"] else "",
              "位置": w["position"]} for w in result_walls["call_walls"]],
            columns=["行权价", "成交量", "IV", "位置"])
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
    parser = argparse.ArgumentParser(description="Put/Call Wall 分析(基于成交量的支撑/阻力)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--date", required=True, help="到期日 YYYY-MM-DD")
    parser.add_argument("--walls", type=int, default=3, help="显示 top N 个 Wall(默认 3)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze_walls(args.symbol, args.date, walls=args.walls, output_json=args.output_json)
    except Exception as e:
        print_error("Put/Call Wall 分析", str(e))
        sys.exit(1)
