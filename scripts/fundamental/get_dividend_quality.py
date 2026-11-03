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
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_dividend_history,
    get_underlying_price,
    market_date,
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
    if price is None or price <= 0:
        raise ValueError(f"无法获取 {symbol} 现价")

    as_of = market_date(symbol)
    try:
        window_start = as_of.replace(year=as_of.year - 1)
    except ValueError:  # 闰日对应上一年的 2 月 28 日
        window_start = as_of.replace(year=as_of.year - 1, day=28)

    records = []
    for row in divs:
        try:
            ex_date = date.fromisoformat(str(row.get("ex_date", "")).replace(".", "-"))
        except ValueError:
            continue
        amount = to_float(row.get("amount"))
        if amount is not None and amount > 0:
            currency = str(row.get("currency") or "").strip().upper() or None
            records.append((ex_date, amount, currency))
    if not records:
        raise ValueError(f"{symbol} 分红记录无法解析(缺少金额或日期)")

    years = defaultdict(list)
    ttm = []
    for ex_date, amount, currency in records:
        if ex_date <= as_of:
            years[ex_date.year].append((amount, currency))
            if ex_date > window_start:
                ttm.append((amount, currency))

    # 仅对能识别报价币种的市场计算收益率。港股存在多币种柜台。
    market = symbol.upper().rsplit(".", 1)[-1]
    quote_currency = {"US": "USD", "SH": "CNY", "SZ": "CNY"}.get(market)
    if market == "HK":
        counter = symbol.split(".")[0].lstrip("0")
        quote_currency = ("CNY" if len(counter) == 5 and counter.startswith("8")
                          else "HKD" if counter.isdigit() and len(counter) <= 4
                          else None)

    def single_currency_sum(payments):
        currencies = {currency for _, currency in payments}
        if len(currencies) != 1 or None in currencies:
            return None, None
        return sum(amount for amount, _ in payments), currencies.pop()

    ttm_by_currency = Counter()
    for amount, currency in ttm:
        ttm_by_currency[currency or "unknown"] += amount
    ttm_total, currency = single_currency_sum(ttm) if ttm else (0.0, quote_currency)
    ttm_yield = (ttm_total / price * 100 if ttm_total is not None
                 and (not ttm or (currency and currency == quote_currency)) else None)

    ys = sorted(years, reverse=True)
    consecutive = 0
    expected_year = as_of.year if as_of.year in years else as_of.year - 1
    while expected_year in years:
        consecutive += 1
        expected_year -= 1

    # 只用最近两个已结束的自然年；数据间断时不输出同比。
    complete_year = as_of.year - 1
    current_total, current_currency = single_currency_sum(years.get(complete_year, []))
    previous_total, previous_currency = single_currency_sum(years.get(complete_year - 1, []))
    growth = ((current_total / previous_total - 1) * 100
              if current_total is not None and previous_total and current_currency == previous_currency
              else None)

    counts = [len(years.get(y, [])) for y in range(complete_year, complete_year - 3, -1)
              if ys and y >= ys[-1]]
    freq_stable = len(set(counts)) == 1 if len(counts) >= 2 else None
    avg_freq = sum(counts) / len(counts) if counts else None

    # 简单评级
    if ttm_yield is None:
        grade = "⚪ 股息率资料不足（币种缺失、不同或未确认）"
    elif ttm_yield >= 4 and consecutive >= 5 and growth is not None and growth >= 0:
        grade = "🟢 达到股息率、连续分红和同比增长阈值"
    elif (ttm_yield or 0) >= 2.5 and consecutive >= 3:
        grade = "🟢 达到股息率和连续分红阈值"
    elif (ttm_yield or 0) >= 2.5:
        grade = "🟡 股息尚可但连续性不足"
    elif (ttm_yield or 0) > 0:
        grade = "⚪ 股息率低于设定阈值"
    else:
        grade = "⚪ 近一年未分红"

    yearly_rows = []
    for year in ys[:8]:
        total, year_currency = single_currency_sum(years[year])
        yearly_rows.append({"年份": year, "每股分红": round(total, 4) if total is not None else None,
                            "币种": year_currency, "期数": len(years[year])})

    result = {
        "symbol": symbol,
        "price": price,
        "currency": currency,
        "quote_currency": quote_currency,
        "quote_currency_source": "market_counter_convention" if quote_currency else None,
        "as_of": as_of.isoformat(),
        "ttm_window_start_exclusive": window_start.isoformat(),
        "ttm_dividend_by_currency": dict(ttm_by_currency),
        "ttm_dividend_per_share": round(ttm_total, 4) if ttm_total is not None else None,
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

    print(f"{symbol} 股息质量(现价 {price} {quote_currency or ''}，截至 {as_of})")
    yield_text = f"{ttm_yield:.2f}%" if ttm_yield is not None else "N/A"
    print(f"  TTM 股息: 每股 {result['ttm_dividend_per_share']} {currency or ''} → 股息率 {yield_text}")
    print(f"  连续分红: {consecutive} 年 | 最新年增长: "
          f"{'N/A' if growth is None else f'{growth:+.1f}%'} | 年均 {avg_freq if avg_freq is not None else 'N/A'} 期"
          f"{'(频率稳定)' if freq_stable else ''}")
    print(f"  评级: {grade}")
    print()
    print("年度分红:")
    print_display_table(yearly_rows, columns=["年份", "每股分红", "币种", "期数"])
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
