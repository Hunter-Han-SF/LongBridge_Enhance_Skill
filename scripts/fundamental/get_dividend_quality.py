"""股息质量分析(股息率 / 连续分红 / 增长 / 稳定性)。

数据源: longbridge dividend(历史分红列表)+ 现价。
适合评估收息型标的(REITs/公用事业/蓝筹)的分红吸引力与可靠性。

指标:
  - 近12个月股息率(TTM yield)= 近一年每股分红合计 ÷ 现价
  - 连续分红年数(按除息年份去重)
  - 年度分红增长率(最近年 vs 上一年)
  - 分红频率稳定性(每年期数是否一致)

用法:
    python get_dividend_quality.py AAPL.US
    python get_dividend_quality.py 0700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_dividend_history,
    get_underlying_price,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def analyze(symbol: str, output_json: bool = False, quiet: bool = False) -> dict:
    divs = get_dividend_history(symbol)
    price = get_underlying_price(symbol)
    if not divs:
        raise ValueError(f"{symbol} 无分红历史(可能从不分红,或非支持市场)")
    if not price:
        raise ValueError(f"无法获取 {symbol} 现价")

    # ex_date 格式实测为 "2026.08.10"
    def _year(d):
        try:
            return int(str(d)[:4])
        except (ValueError, TypeError):
            return None

    def _month(d):
        try:
            return int(str(d)[5:7])
        except (ValueError, TypeError):
            return None

    years = defaultdict(float)   # 年 → 每股分红合计
    per_year_count = defaultdict(int)
    currency = None
    for d in divs:
        y = _year(d.get("ex_date"))
        amt = d.get("amount")
        if y and amt:
            years[y] += amt
            per_year_count[y] += 1
            currency = d.get("currency") or currency

    if not years:
        raise ValueError(f"{symbol} 分红记录无法解析(缺少金额或日期)")

    cur_year = max(years)
    # TTM:最近 12 个月的分红(按 ex_date 在近 12 个月内累加)
    this_year, this_month = cur_year, None
    for d in divs:
        if _year(d.get("ex_date")) == cur_year:
            m = _month(d.get("ex_date"))
            this_month = max(this_month or 0, m or 0)
    ttm_total = 0.0
    for d in divs:
        amt = d.get("amount") or 0
        ey, em = _year(d.get("ex_date")), _month(d.get("ex_date"))
        if not (ey and em):
            continue
        if (ey == cur_year) or (ey == cur_year - 1 and em >= (this_month or 12)):
            ttm_total += amt
    ttm_yield = ttm_total / price * 100 if price else None

    # 连续分红年数(从最新年往前数,允许当年可能尚未派息则从上一年起算)
    ys = sorted(years, reverse=True)
    consecutive = 0
    for i, y in enumerate(ys):
        if i == 0:
            consecutive = 1
        elif ys[i - 1] - y == 1:
            consecutive += 1
        else:
            break

    # 年度增长率:只用完整年份(当年尚未走完,期数不足会误判下滑)
    growth = None
    complete_ys = ys[:]
    latest_count = per_year_count.get(ys[0], 0)
    full_count = per_year_count.get(ys[1], 0) if len(ys) >= 2 else 0
    if len(ys) >= 2 and latest_count < full_count:
        complete_ys = ys[1:]  # 最新年未走完(期数少于上年),从上一年起算
    if len(complete_ys) >= 2 and years[complete_ys[1]]:
        growth = (years[complete_ys[0]] / years[complete_ys[1]] - 1) * 100

    # 频率稳定性
    counts = [per_year_count[y] for y in ys[:3]]
    freq_stable = len(set(counts)) == 1 if len(counts) >= 2 else None
    avg_freq = sum(counts) / len(counts) if counts else 0

    # 简单评级
    if (ttm_yield or 0) >= 4 and consecutive >= 5 and (growth or 0) >= 0:
        grade = "🟢 优质收息标的(高股息+连续+增长)"
    elif (ttm_yield or 0) >= 2.5 and consecutive >= 3:
        grade = "🟢 分红稳定"
    elif (ttm_yield or 0) >= 2.5:
        grade = "🟡 股息尚可但连续性不足"
    elif (ttm_yield or 0) > 0:
        grade = "⚪ 象征性分红(成长型公司常见)"
    else:
        grade = "⚪ 近一年未分红"

    yearly_rows = [{"年份": y, "每股分红": round(years[y], 4), "期数": per_year_count[y]}
                   for y in ys[:8]]

    result = {
        "symbol": symbol,
        "price": price,
        "currency": currency,
        "ttm_dividend_per_share": round(ttm_total, 4),
        "ttm_yield_pct": round(ttm_yield, 2) if ttm_yield is not None else None,
        "consecutive_years": consecutive,
        "yearly_growth_pct": round(growth, 2) if growth is not None else None,
        "avg_periods_per_year": avg_freq,
        "freq_stable": freq_stable,
        "yearly": yearly_rows,
        "records": len(divs),
        "grade": grade,
    }

    if output_json:
        print_json(result)
        return result
    if quiet:
        return result

    print(f"{symbol} 股息质量(现价 {price} {currency or ''})")
    print(f"  TTM 股息: 每股 {result['ttm_dividend_per_share']} → 股息率 {result['ttm_yield_pct']}%")
    print(f"  连续分红: {consecutive} 年 | 最新年增长: "
          f"{'N/A' if growth is None else f'{growth:+.1f}%'} | 年均 {avg_freq:.0f} 期"
          f"{'(频率稳定)' if freq_stable else ''}")
    print(f"  评级: {grade}")
    print()
    print("年度分红:")
    print_display_table([{"年份": r["年份"], "每股分红": r["每股分红"], "期数": r["期数"]}
                         for r in yearly_rows], columns=["年份", "每股分红", "期数"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="股息质量(TTM股息率/连续性/增长)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 0700.HK")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, output_json=args.output_json)
    except Exception as e:
        print_error("股息质量", str(e))
        sys.exit(1)
