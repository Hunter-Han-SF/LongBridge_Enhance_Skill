"""VWAP 分析(现价 vs 当日成交量加权均价)。

数据源: Longbridge intraday 的累计均价 avg_price。

比较日内价格与数据源均价的位置，计算有效分钟中高于均价的比例。

用法:
    python get_vwap_analysis.py AAPL.US
    python get_vwap_analysis.py AAPL.US --date 20260819   # 查历史某日
    python get_vwap_analysis.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_intraday,
    print_error,
    print_json,
    to_float,
)


def _bar_time(row: dict) -> float | None:
    value = row.get("timestamp") or row.get("time")
    numeric = to_float(value)
    if numeric is not None:
        return numeric / 1000 if abs(numeric) >= 1e12 else numeric
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def analyze(symbol: str, date: str | None = None, output_json: bool = False) -> dict:
    rows = get_intraday(symbol, date=date)
    if not rows:
        raise ValueError(f"无分钟线数据。确认 {symbol} 当日(或 {date})有交易。")

    times = [_bar_time(row) for row in rows]
    if all(t is not None for t in times):
        times, rows = zip(*sorted(zip(times, rows), key=lambda pair: pair[0]))

    last = rows[-1]
    price = to_float(last.get("price"))
    vwap = to_float(last.get("avg_price"))
    if price is None or vwap is None or min(price, vwap) <= 0:
        raise ValueError("最新分钟线缺少有效的 price/avg_price 字段")

    dev_pct = (price / vwap - 1) * 100
    vwap_trend = None
    if times[-1] is not None and all(t is not None for t in times):
        target = times[-1] - 30 * 60
        prior = next((r for t, r in reversed(list(zip(times, rows))) if t == target), None)
        vwap_30m_ago = to_float(prior.get("avg_price")) if prior is not None else None
        if vwap_30m_ago is not None and vwap_30m_ago > 0:
            vwap_trend = "上行" if vwap > vwap_30m_ago else ("下行" if vwap < vwap_30m_ago else "走平")

    pairs = [(to_float(r.get("price")), to_float(r.get("avg_price"))) for r in rows]
    valid_pairs = [(p, avg) for p, avg in pairs if p is not None and avg is not None and min(p, avg) > 0]
    above_ratio = sum(p > avg for p, avg in valid_pairs) / len(valid_pairs) * 100
    below_ratio = sum(p < avg for p, avg in valid_pairs) / len(valid_pairs) * 100
    coverage = len(valid_pairs) / len(rows)

    # 仅为分时采样价范围，不能替代完整盘中最高/最低成交价。
    prices = [p for p, _ in pairs if p is not None and p > 0]
    day_high, day_low = max(prices), min(prices)
    vwap_pos = (vwap - day_low) / (day_high - day_low) * 100 if day_high > day_low else None

    if coverage < 0.8 or len(valid_pairs) < 2:
        verdict = "⚪ 有效分钟不足，无法判断日内强弱"
    elif dev_pct > 0.15 and above_ratio >= 60:
        verdict = "🟢 价格持续位于 VWAP 上方"
    elif dev_pct < -0.15 and below_ratio >= 60:
        verdict = "🔴 价格持续位于 VWAP 下方"
    else:
        verdict = "⚪ VWAP 附近拉锯或方向不明确"

    result = {
        "symbol": symbol,
        "date": date or "today",
        "points": len(rows),
        "price": price,
        "vwap": round(vwap, 3),
        "deviation_pct": round(dev_pct, 2),
        "above_vwap_ratio_pct": round(above_ratio, 1),
        "valid_points": len(valid_pairs),
        "coverage_pct": round(coverage * 100, 1),
        "vwap_trend_30m": vwap_trend,
        "day_high": day_high,
        "day_low": day_low,
        "vwap_pos_in_day_range_pct": round(vwap_pos, 1) if vwap_pos is not None else None,
        "verdict": verdict,
        "note": "VWAP 使用 intraday avg_price；覆盖率以返回的分钟为基准。区间基于分时采样价格。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} VWAP 分析({result['date']},{len(rows)} 分钟)")
    print(f"  现价: {price}   VWAP: {round(vwap, 3)}   偏离: {dev_pct:+.2f}%")
    position = f"{vwap_pos:.0f}%" if vwap_pos is not None else "N/A"
    print(f"  分时采样价区间: {day_low} ~ {day_high}(VWAP 相对位置 {position})")
    print(f"  有效分钟中价格在 VWAP 上方: {above_ratio:.0f}%(覆盖 {coverage:.0%})"
          f"   VWAP 近30分钟: {vwap_trend or 'N/A'}")
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
