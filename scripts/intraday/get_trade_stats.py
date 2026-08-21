"""获取成交量按价位分布(近5日 Volume Profile)+ 关键价位分析。

对应 Longbridge CLI: trade-stats <SYMBOL>
模块⑧(日内微观)的核心补位:真实成交筹码分布,比均线支撑阻力更客观。

返回 statistics(近5日均价/主动买卖量)+ trades(每价位的买/卖/中性量)。
加工:
  - POC(Point of Control): 成交量最大的价位(最强支撑/阻力)
  - Value Area(70% 成交区间): 上沿 VAH / 下沿 VAL
  - 每价位主动买卖失衡(买卖压力)

用法:
    python get_trade_stats.py 700.HK
    python get_trade_stats.py AAPL.US
    python get_trade_stats.py 700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_trade_stats,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def analyze_profile(trades: list[dict], value_area_pct: float = 0.70) -> dict:
    """计算 POC 与 Value Area。

    Value Area 算法: 从 POC 开始向成交量更大的一侧逐档扩展,直到覆盖
    value_area_pct 的总成交量(TPO/Market Profile 标准近似)。
    """
    levels = []
    total_vol = 0.0
    for t in trades:
        price = to_float(t.get("price"))
        if price is None:
            continue
        vol = sum(to_float(t.get(k)) or 0
                  for k in ("buy_amount", "sell_amount", "neutral_amount"))
        levels.append({"price": price, "volume": vol,
                       "buy": to_float(t.get("buy_amount")) or 0,
                       "sell": to_float(t.get("sell_amount")) or 0,
                       "neutral": to_float(t.get("neutral_amount")) or 0})
        total_vol += vol
    if not levels or total_vol <= 0:
        return {}

    levels.sort(key=lambda x: x["price"])
    poc = max(levels, key=lambda x: x["volume"])
    target = total_vol * value_area_pct

    i = j = levels.index(poc)
    covered = poc["volume"]
    while covered < target and (i > 0 or j < len(levels) - 1):
        up = levels[i - 1]["volume"] if i > 0 else -1
        down = levels[j + 1]["volume"] if j < len(levels) - 1 else -1
        if up >= down:
            i -= 1
            covered += levels[i]["volume"]
        else:
            j += 1
            covered += levels[j]["volume"]

    total_buy = sum(l["buy"] for l in levels)
    total_sell = sum(l["sell"] for l in levels)
    return {
        "poc": poc["price"],
        "poc_volume": poc["volume"],
        "poc_buy_sell": {"buy": poc["buy"], "sell": poc["sell"]},
        "vah": levels[j]["price"],
        "val": levels[i]["price"],
        "value_area_pct": value_area_pct,
        "levels": len(levels),
        "buy_sell_imbalance": round(total_buy / total_sell, 2) if total_sell else None,
        "levels_detail": levels,
    }


def fetch_trade_stats(symbol: str, output_json: bool = False) -> dict:
    data = get_trade_stats(symbol)
    trades = data.get("trades", [])
    stats = data.get("statistics", {})
    if is_empty(trades):
        raise ValueError(f"无量价分布数据({symbol})。")

    profile = analyze_profile(trades)
    if not profile:
        raise ValueError(f"量价分布数据无有效价位({symbol})。")

    avgprice = to_float(stats.get("avgprice"))
    preclose = to_float(stats.get("preclose"))
    poc, vah, val = profile["poc"], profile["vah"], profile["val"]

    def _position(p: float) -> str:
        if not avgprice:
            return ""
        if p > vah:
            return "价格在 VA 上方(强势,VAH 为支撑)"
        if p < val:
            return "价格在 VA 下方(弱势,VAL 为阻力)"
        return "价格在 VA 内(震荡,看 POC 引力)"

    result = {
        "symbol": symbol,
        "statistics": stats,
        "profile": {k: v for k, v in profile.items() if k != "levels_detail"},
        "position_note": _position(avgprice) if avgprice else "",
        "levels_detail": profile["levels_detail"],
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 量价分布 Volume Profile(近5日,共 {profile['levels']} 个价位)")
    print(f"  POC(最大成交价位): {poc} ← 最强支撑/阻力")
    print(f"  Value Area(70%): {val} ~ {vah}")
    if avgprice:
        print(f"  均价 {avgprice},{_position(avgprice)}")
    if preclose:
        side = "上方" if (avgprice or 0) > preclose else "下方"
        print(f"  昨收 {preclose},均价在其{side}")
    imb = profile.get("buy_sell_imbalance")
    if imb:
        print(f"  主动买/卖量比: {imb}({'买方占优' if imb > 1.1 else '卖方占优' if imb < 0.9 else '均衡'})")
    print()
    detail = sorted(profile["levels_detail"], key=lambda x: x["volume"], reverse=True)[:12]
    detail.sort(key=lambda x: x["price"], reverse=True)
    rows = [{
        "价位": d["price"],
        "成交量": f"{d['volume']:,.0f}",
        "主动买": f"{d['buy']:,.0f}",
        "主动卖": f"{d['sell']:,.0f}",
        "标记": "POC" if d["price"] == poc else ("VAH" if d["price"] == vah
                                                else "VAL" if d["price"] == val else ""),
    } for d in detail]
    print_display_table(rows, columns=["价位", "成交量", "主动买", "主动卖", "标记"])
    print("\n(按成交量取前 12 个价位展示,完整分布用 --json)")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="量价分布 Volume Profile(近5日)")
    parser.add_argument("symbol", help="标的代码,如 700.HK / AAPL.US")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_trade_stats(args.symbol, output_json=args.output_json)
    except Exception as e:
        print_error("获取量价分布", str(e))
        sys.exit(1)
