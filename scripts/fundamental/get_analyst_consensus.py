"""机构/分析师评级共识 + 目标价空间 + EPS 预测分歧度。

数据源: longbridge institution-rating + forecast-eps。

输出三块:
  ① 评级共识: 买入/跑赢/持有/跑输/卖出 人数分布 + 共识结论
  ② 目标价空间: 目标价区间(最高/最低)、共识目标价 vs 现价的上行/下行空间
  ③ EPS 预测: 截至最新日期的共识均值/区间,分歧度 = (最高-最低)/均值(越大不确定性越高)

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
    get_underlying_price_info,
    price_source_note,
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
    instratings = (rating.get("instratings") or {}) if rating else {}

    price = get_underlying_price(symbol)
    hi = to_float(target.get("highest_price"))
    lo = to_float(target.get("lowest_price"))

    # 目标价空间(用区间中值与最高/最低分别算)
    upside_hi = ((hi / price) - 1) * 100 if (hi and price) else None
    downside_lo = ((lo / price) - 1) * 100 if (lo and price) else None
    range_mid = (hi + lo) / 2 if (hi and lo) else None
    # 「中值」优先取服务端的共识目标价(instratings.target,全部分析师的平均目标价)。
    # (最高+最低)/2 只是两个极端值的中点,一个离群分析师就能把它拉偏
    # (实测 AAPL:极端中点 337.5 距现价 -4.5%,共识目标价 345.63 为 -1.0%)。
    consensus = to_float(instratings.get("target"))
    mid = consensus if consensus is not None else range_mid
    mid_source = ("consensus" if consensus is not None
                  else "range_midpoint" if range_mid is not None else None)
    upside_mid = ((mid / price) - 1) * 100 if (mid and price) else None

    # EPS 预测: forecast-eps 返回的不是"未来各报告期",而是共识快照的时间序列
    # (每条 = 截至 forecast_end_date 的最新预测均值/区间,按日期升序,可追溯到数年前;
    # 实测 AAPL 共 343 条,首条为 2018-10-31 的 5.368)。必须取日期最新的一条,
    # 取首条会把多年前已过期的共识当成"下一期预测"。
    def _snapshot_time(item: dict) -> float:
        return (to_float(item.get("forecast_end_date"))
                or to_float(item.get("forecast_start_date")) or 0)

    snapshots = sorted((item for item in get_forecast_eps(symbol) if isinstance(item, dict)),
                       key=_snapshot_time, reverse=True)
    next_fc = None
    dispersion = None
    for item in snapshots:
        mean = to_float(item.get("forecast_eps_mean"))
        if mean:
            hi_e = to_float(item.get("forecast_eps_highest")) or mean
            lo_e = to_float(item.get("forecast_eps_lowest")) or mean
            snapshot_at = item.get("forecast_end_date")
            try:  # Unix 时间戳转可读日期
                snapshot_at = datetime.fromtimestamp(int(snapshot_at), tz=timezone.utc).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                pass
            next_fc = {"as_of": snapshot_at,
                       # period_end 为历史键名,保留以兼容既有调用方;值是快照日期
                       "period_end": snapshot_at, "mean": mean,
                       "highest": hi_e, "lowest": lo_e,
                       "median": to_float(item.get("forecast_eps_median"))}
            dispersion = (hi_e - lo_e) / abs(mean) * 100 if mean else None
            next_fc["dispersion_pct"] = round(dispersion, 1) if dispersion is not None else None
            break

    result = {
        "symbol": symbol,
        "price": price,
        "underlying_price_source": get_underlying_price_info(symbol),
        "rating": {
            "buy": ev.get("buy"), "over": ev.get("over"), "hold": ev.get("hold"),
            "under": ev.get("under"), "sell": ev.get("sell"), "total": ev.get("total"),
            "label": _consensus_label(ev),
            "industry": {"name": analyst.get("industry_name"),
                         "rank": analyst.get("industry_rank"),
                         "total": analyst.get("industry_total")},
        },
        "target_price": {
            "highest": hi, "lowest": lo,
            "consensus": consensus,
            "range_midpoint": round(range_mid, 4) if range_mid is not None else None,
            "mid": mid, "mid_source": mid_source,
            "upside_to_highest_pct": round(upside_hi, 1) if upside_hi is not None else None,
            "upside_to_mid_pct": round(upside_mid, 1) if upside_mid is not None else None,
            "downside_to_lowest_pct": round(downside_lo, 1) if downside_lo is not None else None,
        },
        "eps_forecast": next_fc,
        "note": ("over/under = 跑赢/跑输大盘(买入/卖出倾向)。分歧度 = (最高-最低)/均值。"
                 "EPS 预测是截至 as_of 日期的最新共识快照,不是某一报告期的预测。"
                 "target_price.mid 优先为共识目标价(mid_source=consensus),"
                 "服务端未给出时退回(最高+最低)/2(mid_source=range_midpoint)。"),
    }

    if output_json:
        print_json(result)
        return result
    if quiet:
        return result

    print(f"{symbol} 分析师共识(现价 {price}{price_source_note(symbol)})")
    r = result["rating"]
    print(f"  评级分布: 买入 {r['buy']} / 跑赢 {r['over']} / 持有 {r['hold']} "
          f"/ 跑输 {r['under']} / 卖出 {r['sell']}(共 {r['total']} 家)→ {r['label']}")
    if analyst.get("industry_name"):
        print(f"  行业: {analyst['industry_name']}(综合排名 {analyst.get('industry_rank')}"
              f"/{analyst.get('industry_total')})")
    t = result["target_price"]
    if t["highest"]:
        print(f"  目标价: {t['lowest']} ~ {t['highest']}(共识目标价 {t['mid']})")
        print(f"    → 距最高目标 {t['upside_to_highest_pct']:+.1f}% / 距共识目标 {t['upside_to_mid_pct']:+.1f}% "
              f"/ 距最低目标 {t['downside_to_lowest_pct']:+.1f}%")
    if next_fc:
        print(f"  EPS 预测(截至 {next_fc['as_of']} 的最新共识): 均值 {next_fc['mean']} "
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
