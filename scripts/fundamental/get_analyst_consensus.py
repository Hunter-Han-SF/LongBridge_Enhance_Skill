"""机构/分析师评级共识 + 目标价空间 + EPS 预测分歧度。

数据源: longbridge institution-rating + forecast-eps。

输出三块:
  ① 评级共识: 买入/跑赢/持有/跑输/卖出 人数分布 + 共识结论
  ② 目标价空间: 目标价区间(最高/最低) vs 现价的上行/下行空间
  ③ EPS 预测: 下一期预测均值/区间,分歧度 = (最高-最低)/均值(越大不确定性越高)

用法:
    python get_analyst_consensus.py AAPL.US
    python get_analyst_consensus.py TSLA.US --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_forecast_eps,
    get_institution_rating,
    get_underlying_price,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _consensus_label(ev: dict) -> str:
    total = to_float(ev.get("total"), 0) or 0
    if total <= 0:
        return "无评级"
    bull = (to_float(ev.get("buy"), 0) or 0) + (to_float(ev.get("over"), 0) or 0)
    bear = (to_float(ev.get("sell"), 0) or 0) + (to_float(ev.get("under"), 0) or 0)
    ratio = bull / total
    if ratio >= 0.7:
        return "🟢 强烈看多"
    if ratio >= 0.5:
        return "🟢 偏多"
    if bear / total >= 0.4:
        return "🔴 偏空"
    return "⚪ 分歧/中性"


def analyze(symbol: str, output_json: bool = False, quiet: bool = False) -> dict:
    rating = get_institution_rating(symbol)
    analyst = (rating.get("analyst") or {}) if rating else {}
    ev = analyst.get("evaluate") or {}
    target = analyst.get("target") or {}

    price = get_underlying_price(symbol)
    hi = to_float(target.get("highest_price"))
    lo = to_float(target.get("lowest_price"))

    # 目标价空间(用区间中值与最高/最低分别算)
    upside_hi = ((hi / price) - 1) * 100 if (hi and price) else None
    downside_lo = ((lo / price) - 1) * 100 if (lo and price) else None
    mid = (hi + lo) / 2 if (hi and lo) else None
    upside_mid = ((mid / price) - 1) * 100 if (mid and price) else None

    # EPS 预测(取最近一个未来期)
    fc = get_forecast_eps(symbol)
    next_fc = None
    dispersion = None
    for item in fc:  # items 通常按期倒序/正序都有,取含均值的最新一条
        mean = to_float(item.get("forecast_eps_mean"))
        if mean:
            hi_e = to_float(item.get("forecast_eps_highest")) or mean
            lo_e = to_float(item.get("forecast_eps_lowest")) or mean
            period_end = item.get("forecast_end_date")
            try:  # Unix 时间戳转可读日期
                period_end = datetime.fromtimestamp(int(period_end), tz=timezone.utc).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                pass
            next_fc = {"period_end": period_end, "mean": mean,
                       "highest": hi_e, "lowest": lo_e,
                       "median": to_float(item.get("forecast_eps_median"))}
            dispersion = (hi_e - lo_e) / abs(mean) * 100 if mean else None
            next_fc["dispersion_pct"] = round(dispersion, 1) if dispersion is not None else None
            break

    result = {
        "symbol": symbol,
        "price": price,
        "rating": {
            "buy": ev.get("buy"), "over": ev.get("over"), "hold": ev.get("hold"),
            "under": ev.get("under"), "sell": ev.get("sell"), "total": ev.get("total"),
            "label": _consensus_label(ev),
            "industry": {"name": analyst.get("industry_name"),
                         "rank": analyst.get("industry_rank"),
                         "total": analyst.get("industry_total")},
        },
        "target_price": {
            "highest": hi, "lowest": lo, "mid": mid,
            "upside_to_highest_pct": round(upside_hi, 1) if upside_hi is not None else None,
            "upside_to_mid_pct": round(upside_mid, 1) if upside_mid is not None else None,
            "downside_to_lowest_pct": round(downside_lo, 1) if downside_lo is not None else None,
        },
        "eps_forecast": next_fc,
        "note": "over/under = 跑赢/跑输大盘(买入/卖出倾向)。分歧度 = (最高-最低)/均值。",
    }

    if output_json:
        print_json(result)
        return result
    if quiet:
        return result

    print(f"{symbol} 分析师共识(现价 {price})")
    r = result["rating"]
    print(f"  评级分布: 买入 {r['buy']} / 跑赢 {r['over']} / 持有 {r['hold']} "
          f"/ 跑输 {r['under']} / 卖出 {r['sell']}(共 {r['total']} 家)→ {r['label']}")
    if analyst.get("industry_name"):
        print(f"  行业: {analyst['industry_name']}(综合排名 {analyst.get('industry_rank')}"
              f"/{analyst.get('industry_total')})")
    t = result["target_price"]
    if t["highest"]:
        print(f"  目标价: {t['lowest']} ~ {t['highest']}(中值 {t['mid']})")
        print(f"    → 距最高目标 {t['upside_to_highest_pct']:+.1f}% / 距中值 {t['upside_to_mid_pct']:+.1f}% "
              f"/ 距最低目标 {t['downside_to_lowest_pct']:+.1f}%")
    if next_fc:
        print(f"  EPS 预测(至 {next_fc['period_end']}): 均值 {next_fc['mean']} "
              f"(区间 {next_fc['lowest']}~{next_fc['highest']})")
        print(f"    → 分歧度 {next_fc['dispersion_pct']}%"
              f"({'高,不确定性大' if (next_fc['dispersion_pct'] or 0) > 30 else '适中'})")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="分析师评级共识 + 目标价空间 + EPS 预测")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, output_json=args.output_json)
    except Exception as e:
        print_error("分析师共识", str(e))
        sys.exit(1)
