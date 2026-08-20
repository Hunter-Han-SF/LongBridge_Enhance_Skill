"""逐笔主动买卖比(Order Flow,基于逐笔成交方向)。

数据源: longbridge trades(direction: Up=主动买 / Down=主动卖)。

与 capital(大中小单快照)互补,这是逐笔粒度的真实成交方向:
  - 主动买入占比(买方主动吃卖盘的力度)
  - 金额加权买卖比(大单权重更高)
  - 大单统计(≥阈值的主动买/卖笔数与金额)
  - 尾盘 N 笔的方向(短线情绪)

用法:
    python get_trade_flow.py AAPL.US
    python get_trade_flow.py TSLA.US --count 500 --big 2000 --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_trades,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def analyze(symbol: str, count: int = 300, big_size: float = 1000,
            output_json: bool = False) -> dict:
    trades = get_trades(symbol, count=count)
    if not trades:
        raise ValueError(f"无逐笔成交数据。{symbol} 可能休市或不支持。")

    # direction: Up=主动买, Down=主动卖, 其他(Flat)不计入方向
    buy_vol = sell_vol = 0.0
    buy_amt = sell_amt = 0.0
    buy_n = sell_n = 0
    big_buys, big_sells = [], []
    for t in trades:
        vol = to_float(t.get("volume"), 0) or 0
        px = to_float(t.get("price"), 0) or 0
        amt = vol * px
        d = str(t.get("direction", "")).lower()
        if d == "up":
            buy_vol += vol
            buy_amt += amt
            buy_n += 1
            if vol >= big_size:
                big_buys.append({"price": px, "volume": vol, "time": t.get("time")})
        elif d == "down":
            sell_vol += vol
            sell_amt += amt
            sell_n += 1
            if vol >= big_size:
                big_sells.append({"price": px, "volume": vol, "time": t.get("time")})

    total_dir_vol = buy_vol + sell_vol
    buy_ratio = buy_vol / total_dir_vol * 100 if total_dir_vol else None
    amt_ratio = buy_amt / (buy_amt + sell_amt) * 100 if (buy_amt + sell_amt) else None

    # 尾盘(最近30笔)方向
    tail = trades[:30]  # trades 按时间倒序(最新在前)
    tail_buy = sum(1 for t in tail if str(t.get("direction", "")).lower() == "up")
    tail_sell = sum(1 for t in tail if str(t.get("direction", "")).lower() == "down")
    tail_mood = None
    if tail_buy + tail_sell:
        tp = tail_buy / (tail_buy + tail_sell) * 100
        tail_mood = "偏买 🟢" if tp > 60 else ("偏卖 🔴" if tp < 40 else "均衡 ⚪")

    if buy_ratio is None:
        verdict = "⚪ 无方向性成交"
    elif buy_ratio >= 60:
        verdict = "🟢 主动买占优(买方吃单积极)"
    elif buy_ratio <= 40:
        verdict = "🔴 主动卖占优(卖方砸单积极)"
    else:
        verdict = "⚪ 多空均衡"

    big_rows = [{"方向": "🟢 大单买", **b} for b in big_buys[:5]] + \
               [{"方向": "🔴 大单卖", **s} for s in big_sells[:5]]

    result = {
        "symbol": symbol,
        "trades": len(trades),
        "buy_volume": buy_vol, "sell_volume": sell_vol,
        "buy_count": buy_n, "sell_count": sell_n,
        "buy_volume_ratio_pct": round(buy_ratio, 1) if buy_ratio is not None else None,
        "buy_amount_ratio_pct": round(amt_ratio, 1) if amt_ratio is not None else None,
        "big_threshold": big_size,
        "big_buys": len(big_buys), "big_sells": len(big_sells),
        "big_buy_amount": round(sum(b["price"] * b["volume"] for b in big_buys), 0),
        "big_sell_amount": round(sum(s["price"] * s["volume"] for s in big_sells), 0),
        "tail_mood": tail_mood,
        "verdict": verdict,
        "note": "Up=主动买/Down=主动卖(按 tick 方向);大单阈值为股数,不同价位标的需调整。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 逐笔主动买卖(近 {len(trades)} 笔)")
    print(f"  主动买: {buy_vol:,.0f} 股 / {buy_n} 笔    主动卖: {sell_vol:,.0f} 股 / {sell_n} 笔")
    if buy_ratio is not None:
        print(f"  买入量占比: {buy_ratio:.1f}%(金额口径 {amt_ratio:.1f}%)")
    print(f"  大单(≥{big_size:.0f}股): 买 {len(big_buys)} 笔 vs 卖 {len(big_sells)} 笔")
    if tail_mood:
        print(f"  尾盘情绪(近30笔): {tail_mood}")
    print(f"  判断: {verdict}")
    if big_rows:
        print()
        print("大单明细(最多各5笔):")
        print_display_table(
            [{"方向": r["方向"], "价格": r["price"], "数量": r["volume"], "时间": (r.get("time") or "")[-8:]}
             for r in big_rows], columns=["方向", "价格", "数量", "时间"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="逐笔主动买卖比(Order Flow)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 0700.HK")
    parser.add_argument("--count", type=int, default=300, help="取样笔数(默认 300,最大 1000)")
    parser.add_argument("--big", type=float, default=1000, help="大单阈值(股,默认 1000)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, count=args.count, big_size=args.big, output_json=args.output_json)
    except Exception as e:
        print_error("主动买卖比", str(e))
        sys.exit(1)
