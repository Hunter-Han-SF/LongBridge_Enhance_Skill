"""盘口买卖压力(L2 深度失衡分析)。

数据源: longbridge depth(买卖五档/多档梯子)。

指标:
  - 买卖盘量比 = Σ买档挂量 / Σ卖档挂量(>1 买盘厚,<1 卖盘厚)
  - 失衡率 =(买-卖)/(买+卖)(-1 ~ +1)
  - 最大挂单墙(买/卖各档中的最大挂量价位,常为隐形支撑/阻力)
  - 加权买卖价差(挂量加权的中枢价)

⚠️ 盘口是瞬时快照,只反映挂单意愿,不保证成交;收盘后数据为最后快照。

用法:
    python get_orderbook_pressure.py AAPL.US
    python get_orderbook_pressure.py 0700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_depth,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def analyze(symbol: str, output_json: bool = False) -> dict:
    book = get_depth(symbol)
    bids, asks = book.get("bids", []), book.get("asks", [])
    if not bids and not asks:
        raise ValueError(f"无盘口数据。{symbol} 可能未开盘或市场休市。")

    def _vol(rows):
        return [to_float(r.get("volume"), 0) or 0 for r in rows]

    def _px(rows):
        return [to_float(r.get("price")) for r in rows]

    bid_vols, ask_vols = _vol(bids), _vol(asks)
    total_bid, total_ask = sum(bid_vols), sum(ask_vols)
    ratio = total_bid / total_ask if total_ask else None
    imbalance = ((total_bid - total_ask) / (total_bid + total_ask)
                 if (total_bid + total_ask) else None)

    # 最大挂单墙
    bid_wall = max(bids, key=lambda r: to_float(r.get("volume"), 0) or 0) if bids else None
    ask_wall = max(asks, key=lambda r: to_float(r.get("volume"), 0) or 0) if asks else None

    # 挂量加权中枢价
    center = None
    if bids and asks:
        num = sum(p * v for p, v in zip(_px(bids), bid_vols) if p) + \
              sum(p * v for p, v in zip(_px(asks), ask_vols) if p)
        den = sum(bid_vols) + sum(ask_vols)
        center = num / den if den else None

    # 买卖价差
    spread = None
    spread_pct = None
    if bids and asks:
        best_bid = to_float(bids[0].get("price"))
        best_ask = to_float(asks[0].get("price"))
        if best_bid and best_ask:
            spread = round(best_ask - best_bid, 4)
            spread_pct = spread / best_ask * 100

    if imbalance is None:
        verdict = "⚪ 无有效挂单"
    elif imbalance > 0.3:
        verdict = "🟢 买盘显著占优(下方承接厚)"
    elif imbalance > 0.1:
        verdict = "🟢 买盘略占优"
    elif imbalance < -0.3:
        verdict = "🔴 卖盘显著占优(上方压制重)"
    elif imbalance < -0.1:
        verdict = "🔴 卖盘略占优"
    else:
        verdict = "⚪ 买卖盘均衡"

    result = {
        "symbol": symbol,
        "levels": {"bids": len(bids), "asks": len(asks)},
        "total_bid_volume": total_bid,
        "total_ask_volume": total_ask,
        "bid_ask_volume_ratio": round(ratio, 2) if ratio else None,
        "imbalance": round(imbalance, 3) if imbalance is not None else None,
        "bid_wall": {"price": bid_wall.get("price"), "volume": bid_wall.get("volume")} if bid_wall else None,
        "ask_wall": {"price": ask_wall.get("price"), "volume": ask_wall.get("volume")} if ask_wall else None,
        "volume_weighted_center": round(center, 3) if center else None,
        "spread": spread,
        "spread_pct": round(spread_pct, 3) if spread_pct is not None else None,
        "verdict": verdict,
        "note": "瞬时快照,收盘后为最后盘口。挂单可随时撤单,仅反映意愿。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 盘口压力(买 {len(bids)} 档 / 卖 {len(asks)} 档)")
    print(f"  买盘总量: {total_bid:,.0f}   卖盘总量: {total_ask:,.0f}   "
          f"量比: {ratio:.2f}" if ratio else "  盘口单边为空")
    print(f"  失衡率: {imbalance:+.2f}(-1 全卖盘 ~ +1 全买盘)")
    if spread is not None:
        print(f"  买卖价差: {spread}({spread_pct:.3f}%)")
    if center:
        print(f"  挂量加权中枢: {center}")
    if bid_wall:
        print(f"  最大买单墙: {bid_wall['price']} × {to_float(bid_wall['volume']):,.0f}(隐形支撑)")
    if ask_wall:
        print(f"  最大卖单墙: {ask_wall['price']} × {to_float(ask_wall['volume']):,.0f}(隐形阻力)")
    print(f"  判断: {verdict}")
    if bids:
        print()
        print("买档:")
        print_display_table([{"档位": r.get("position"), "价格": r.get("price"),
                              "挂量": r.get("volume")} for r in bids[:5]],
                            columns=["档位", "价格", "挂量"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="盘口买卖压力(L2 深度失衡)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 0700.HK")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, output_json=args.output_json)
    except Exception as e:
        print_error("盘口压力", str(e))
        sys.exit(1)
