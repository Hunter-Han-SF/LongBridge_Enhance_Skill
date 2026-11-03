"""基于逐笔成交价格方向估计成交压力（tick rule）。

Longbridge trades 的 Up/Down 表示相对前笔价格的方向。
按已分类股数、可用成交额与最近 30 笔统计估计压力。

用法:
    python get_trade_flow.py AAPL.US
    python get_trade_flow.py TSLA.US --count 500 --big 2000 --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_trades,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _trade_time(trade: dict) -> datetime | None:
    value = trade.get("timestamp")
    if value is None or value == "":
        value = trade.get("time")
    numeric = to_float(value)
    try:
        if numeric is not None:
            seconds = numeric / 1000 if abs(numeric) >= 1e12 else numeric
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (OverflowError, OSError, ValueError):
        return None


def _display_trade_time(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    if value.tzinfo is None:
        return f"{value:%H:%M:%S}（来源时区未标明）"
    return value.astimezone(timezone.utc).strftime("%H:%M:%S UTC")


def analyze(symbol: str, count: int = 300, big_size: float = 1000,
            output_json: bool = False) -> dict:
    trades = get_trades(symbol, count=count)
    if not trades:
        raise ValueError(f"无逐笔成交数据。{symbol} 可能休市或不支持。")

    # Up/Down 是价格方向。平价和未知方向保留为未分类。
    buy_vol = sell_vol = 0.0
    buy_amt = sell_amt = 0.0
    buy_n = sell_n = 0
    unclassified_vol = total_volume = 0.0
    big_buys, big_sells = [], []
    for t in trades:
        vol = to_float(t.get("volume"))
        if vol is None or vol <= 0:
            continue
        total_volume += vol
        px = to_float(t.get("price"))
        px = px if px is not None and px > 0 else None
        amt = vol * px if px is not None else 0.0
        d = str(t.get("direction", "")).lower()
        if d == "up":
            buy_vol += vol
            buy_amt += amt
            buy_n += 1
            if vol >= big_size:
                big_buys.append({"price": px, "volume": vol, "time": _trade_time(t)})
        elif d == "down":
            sell_vol += vol
            sell_amt += amt
            sell_n += 1
            if vol >= big_size:
                big_sells.append({"price": px, "volume": vol, "time": _trade_time(t)})

        else:
            unclassified_vol += vol

    total_dir_vol = buy_vol + sell_vol
    buy_ratio = buy_vol / total_dir_vol * 100 if total_dir_vol else None
    amt_ratio = buy_amt / (buy_amt + sell_amt) * 100 if (buy_amt + sell_amt) else None

    # 混用带时区与未标时区的时间时，无法可靠比较先后。
    timed = [(_trade_time(t), t) for t in trades]
    comparable = (all(ts is not None for ts, _ in timed)
                  and len({ts.tzinfo is not None for ts, _ in timed}) == 1)
    tail = ([t for _, t in sorted(timed, key=lambda pair: pair[0], reverse=True)[:30]]
            if comparable else [])
    tail_buy = sum(1 for t in tail if str(t.get("direction", "")).lower() == "up")
    tail_sell = sum(1 for t in tail if str(t.get("direction", "")).lower() == "down")
    tail_mood = None
    if tail_buy + tail_sell:
        tp = tail_buy / (tail_buy + tail_sell) * 100
        tail_mood = "偏买 🟢" if tp > 60 else ("偏卖 🔴" if tp < 40 else "均衡 ⚪")

    if buy_ratio is None:
        verdict = "⚪ 无可分类成交量"
    elif buy_ratio >= 60:
        verdict = "🟢 上跳成交量占优（估计买方压力）"
    elif buy_ratio <= 40:
        verdict = "🔴 下跳成交量占优（估计卖方压力）"
    else:
        verdict = "⚪ 上下跳成交量接近"

    big_rows = [{"方向": "🟢 上跳大单", **b} for b in big_buys[:5]] + \
               [{"方向": "🔴 下跳大单", **s} for s in big_sells[:5]]

    result = {
        "symbol": symbol,
        "trades": len(trades),
        "direction_method": "price_tick_rule",
        "unclassified_volume": unclassified_vol,
        "unclassified_volume_ratio_pct": (round(unclassified_vol / total_volume * 100, 1)
                                          if total_volume else None),
        "buy_volume": buy_vol, "sell_volume": sell_vol,
        "buy_count": buy_n, "sell_count": sell_n,
        "buy_volume_ratio_pct": round(buy_ratio, 1) if buy_ratio is not None else None,
        "buy_amount_ratio_pct": round(amt_ratio, 1) if amt_ratio is not None else None,
        "big_threshold": big_size,
        "big_buys": len(big_buys), "big_sells": len(big_sells),
        "big_buy_amount": round(sum(b["price"] * b["volume"] for b in big_buys if b["price"] is not None), 0),
        "big_sell_amount": round(sum(s["price"] * s["volume"] for s in big_sells if s["price"] is not None), 0),
        "tail_mood": tail_mood,
        "verdict": verdict,
        "note": "buy/sell 字段为上跳/下跳估计值。未分类量不进方向分母，缺价成交不进金额分母。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 逐笔成交压力估计(近 {len(trades)} 笔)")
    print(f"  上跳: {buy_vol:,.0f} 股 / {buy_n} 笔    下跳: {sell_vol:,.0f} 股 / {sell_n} 笔")
    if buy_ratio is not None:
        amount_text = f"{amt_ratio:.1f}%" if amt_ratio is not None else "N/A"
        print(f"  上跳股数占比: {buy_ratio:.1f}%(上跳金额占比 {amount_text})")
    if total_volume:
        print(f"  未分类成交量占比: {result['unclassified_volume_ratio_pct']:.1f}%")
    print(f"  大单(≥{big_size:.0f}股): 上跳 {len(big_buys)} 笔 vs 下跳 {len(big_sells)} 笔")
    if tail_mood:
        print(f"  最近30笔方向估计: {tail_mood}")
    print(f"  判断: {verdict}")
    if big_rows:
        print()
        print("大单明细(最多各5笔):")
        print_display_table(
            [{"方向": r["方向"], "价格": r["price"], "数量": r["volume"], "时间": _display_trade_time(r["time"])}
             for r in big_rows], columns=["方向", "价格", "数量", "时间"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="按逐笔成交价格方向估计成交压力")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 0700.HK")
    parser.add_argument("--count", type=int, default=300, help="取样笔数(默认 300,最大 1000)")
    parser.add_argument("--big", type=float, default=1000, help="大单阈值(股,默认 1000)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, count=args.count, big_size=args.big, output_json=args.output_json)
    except Exception as e:
        print_error("逐笔成交压力", str(e))
        sys.exit(1)
