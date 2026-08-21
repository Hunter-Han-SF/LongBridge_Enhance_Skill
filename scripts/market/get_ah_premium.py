"""获取 A/H 溢价(两地上市股的价差监控,仅 A+H 股)。

对应 Longbridge CLI: ah-premium <SYMBOL> [--kline-type] / ah-premium intraday <SYMBOL>
⚠️ 仅对 A+H 两地上市的港股有效(如 939.HK/1398.HK/700.HK 不适用则报无数据)。

ahpremium_rate 含义(实测):
  -0.266 = H 股价格比 A 股低 26.6%(H 折价,A 溢价)
   正值 = H 股比 A 股贵(A 折价,罕见)
趋势:溢价收窄 = 相对看好 H;溢价走阔 = 资金偏好 A。

用法:
    python get_ah_premium.py 939.HK                       # 日线历史+统计
    python get_ah_premium.py 939.HK --count 60
    python get_ah_premium.py 939.HK --kline-type week
    python get_ah_premium.py 939.HK --intraday            # 当日分时
    python get_ah_premium.py 939.HK --json
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_ah_premium,
    get_ah_premium_intraday,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _ts_to_date(ts) -> str:
    f = to_float(ts)
    if not f:
        return ""
    return datetime.fromtimestamp(f, tz=timezone.utc).strftime("%Y-%m-%d")


def _analyze(rows: list[dict]) -> dict:
    rates = [to_float(r.get("ahpremium_rate")) for r in rows]
    rates = [r for r in rates if r is not None]
    if not rates:
        return {}
    latest = rates[-1]
    mean = sum(rates) / len(rates)
    half = len(rates) // 2 or 1
    first_half = sum(rates[:half]) / half
    second_half = sum(rates[-half:]) / half
    trend = second_half - first_half
    return {
        "latest": round(latest, 4),
        "mean": round(mean, 4),
        "max": round(max(rates), 4),
        "min": round(min(rates), 4),
        "zscore": round((latest - mean) / (statistics.pstdev(rates) or 1), 2)
            if len(rates) >= 3 else None,
        "trend": {"direction": "溢价收窄(H相对走强)" if trend > 0 else "溢价走阔(A相对走强)",
                   "change": round(trend, 4)},
        "note": "rate<0 表示 H 股折价;zscore>1 表示当前折价深于均值(潜在修复机会)",
    }


def fetch_ah_premium(symbol: str, count: int = 60, kline_type: str = "day",
                     intraday: bool = False, output_json: bool = False) -> dict:
    if intraday:
        rows = get_ah_premium_intraday(symbol)
        mode = "intraday"
    else:
        rows = get_ah_premium(symbol, count=count, kline_type=kline_type)
        mode = kline_type
    if is_empty(rows):
        raise ValueError(f"无 A/H 溢价数据({symbol})。仅 A+H 两地上市的港股支持"
                         f"(如 939.HK/1398.HK/2628.HK)。")

    analysis = _analyze(rows)
    result = {"symbol": symbol, "mode": mode, "points": len(rows),
              "analysis": analysis, "klines": rows}

    if output_json:
        print_json(result)
        return result

    a = analysis or {}
    print(f"{symbol} A/H 溢价({mode},{len(rows)} 个数据点)")
    if a:
        print(f"  当前: {a['latest']:+.2%}(H股{'折价' if a['latest'] < 0 else '溢价'})"
              f" | 均值 {a['mean']:+.2%} | 区间 [{a['min']:+.2%}, {a['max']:+.2%}]")
        if a.get("zscore") is not None:
            print(f"  z-score {a['zscore']}(相对均值位置) | 趋势: {a['trend']['direction']}"
                  f"({a['trend']['change']:+.2%})")
    print()
    show = rows[-15:]
    table = [{
        "日期": _ts_to_date(r.get("timestamp")) or str(r.get("timestamp", "")),
        "A价": r.get("aprice", ""),
        "H价": r.get("hprice", ""),
        "汇率": r.get("currency_rate", ""),
        "溢价率": f"{to_float(r.get('ahpremium_rate')) or 0:+.2%}"
            if to_float(r.get("ahpremium_rate")) is not None else "",
    } for r in show]
    print_display_table(table, columns=["日期", "A价", "H价", "汇率", "溢价率"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A/H 溢价监控(仅A+H两地上市)")
    parser.add_argument("symbol", help="港股代码,如 939.HK")
    parser.add_argument("--count", type=int, default=60, help="K 线数量(默认 60)")
    parser.add_argument("--kline-type", default="day",
                        choices=["1m", "5m", "15m", "30m", "60m", "day", "week", "month", "year"],
                        help="K 线类型(默认 day)")
    parser.add_argument("--intraday", action="store_true", help="当日分时模式")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_ah_premium(symbol=args.symbol, count=args.count, kline_type=args.kline_type,
                         intraday=args.intraday, output_json=args.output_json)
    except Exception as e:
        print_error("获取 A/H 溢价", str(e))
        sys.exit(1)
