"""VWAP 分析(现价 vs 当日成交量加权均价)。

数据源: longbridge intraday(分钟线自带 avg_price,即交易所口径 VWAP)。

VWAP 是日内多空分水岭:
  - 价格持续在 VWAP 上方 = 买方主导(当日强势),回踩 VWAP 常有支撑
  - 价格在 VWAP 下方 = 卖方主导(当日弱势),反抽 VWAP 常有压力
  - 机构执行算法常以 VWAP 为基准(跑赢/跑输 VWAP 衡量执行质量)

用法:
    python get_vwap_analysis.py AAPL.US
    python get_vwap_analysis.py AAPL.US --date 20260819   # 查历史某日
    python get_vwap_analysis.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_intraday,
    print_error,
    print_json,
    to_float,
)


def analyze(symbol: str, date: str | None = None, output_json: bool = False) -> dict:
    rows = get_intraday(symbol, date=date)
    if not rows:
        raise ValueError(f"无分钟线数据。确认 {symbol} 当日(或 {date})有交易。")

    last = rows[-1]
    price = to_float(last.get("price"))
    vwap = to_float(last.get("avg_price"))
    if not price or not vwap:
        raise ValueError("分钟线缺少 price/avg_price 字段")

    dev_pct = (price / vwap - 1) * 100
    # VWAP 趋势:对比 30 分钟前后的 VWAP
    vwap_trend = None
    if len(rows) >= 60:
        vwap_30m_ago = to_float(rows[-30].get("avg_price"))
        vwap_open = to_float(rows[0].get("avg_price"))
        if vwap_30m_ago and vwap_open:
            vwap_trend = "上行" if vwap > vwap_30m_ago else ("下行" if vwap < vwap_30m_ago else "走平")

    # 价格在 VWAP 上方的时间占比(当日强弱持续性)
    above = sum(1 for r in rows if to_float(r.get("price")) and to_float(r.get("avg_price"))
                and to_float(r["price"]) >= to_float(r["avg_price"]))
    above_ratio = above / len(rows) * 100

    # 当日高低与 VWAP 位置
    prices = [to_float(r.get("price")) for r in rows]
    prices = [p for p in prices if p]
    day_high, day_low = max(prices), min(prices)
    vwap_pos = (vwap - day_low) / (day_high - day_low) * 100 if day_high > day_low else 50

    if dev_pct > 0.15 and above_ratio >= 60:
        verdict = "🟢 买方主导(价格站稳 VWAP 上方)"
    elif dev_pct < -0.15 and above_ratio <= 40:
        verdict = "🔴 卖方主导(价格压在 VWAP 下方)"
    else:
        verdict = "⚪ 围绕 VWAP 拉锯(方向不明)"

    result = {
        "symbol": symbol,
        "date": date or "today",
        "points": len(rows),
        "price": price,
        "vwap": round(vwap, 3),
        "deviation_pct": round(dev_pct, 2),
        "above_vwap_ratio_pct": round(above_ratio, 1),
        "vwap_trend_30m": vwap_trend,
        "day_high": day_high,
        "day_low": day_low,
        "vwap_pos_in_day_range_pct": round(vwap_pos, 1),
        "verdict": verdict,
        "note": "VWAP 取自 intraday avg_price(交易所口径)。上方时间占比衡量强弱持续性。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} VWAP 分析({result['date']},{len(rows)} 分钟)")
    print(f"  现价: {price}   VWAP: {round(vwap, 3)}   偏离: {dev_pct:+.2f}%")
    print(f"  当日区间: {day_low} ~ {day_high}(VWAP 位于区间 {vwap_pos:.0f}% 处)")
    print(f"  价格在 VWAP 上方时间占比: {above_ratio:.0f}%   VWAP 近30分钟: {vwap_trend or 'N/A'}")
    print(f"  判断: {verdict}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VWAP 分析(现价 vs 当日均价)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US")
    parser.add_argument("--date", default=None, help="历史日期 YYYYMMDD(默认今天)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, date=args.date, output_json=args.output_json)
    except Exception as e:
        print_error("VWAP 分析", str(e))
        sys.exit(1)
