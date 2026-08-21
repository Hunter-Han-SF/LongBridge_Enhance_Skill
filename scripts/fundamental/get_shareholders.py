"""获取机构股东列表(含持仓变动)+ 集中度分析。

对应 Longbridge CLI: shareholder <SYMBOL>
加工:机构合计持股比例、增减持家数、新进/退出。

用法:
    python get_shareholders.py AAPL.US
    python get_shareholders.py AAPL.US --count 10
    python get_shareholders.py 700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_shareholders,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def fetch_shareholders(symbol: str, count: int = 15, output_json: bool = False) -> dict:
    holders = get_shareholders(symbol)
    if is_empty(holders):
        raise ValueError(f"无股东数据({symbol})。")

    for h in holders:
        chg = to_float(h.get("shares_changed"))
        h["direction"] = ("增持" if (chg or 0) > 0 else
                          "减持" if (chg or 0) < 0 else "不变") if chg is not None else ""
        stock = (h.get("stocks") or [{}])[0]
        h["holder_symbol"] = stock.get("code", "")
        h["holder_chg"] = stock.get("chg", "")

    total_pct = sum(to_float(h.get("percent_of_shares")) or 0 for h in holders)
    inc = sum(1 for h in holders if h.get("direction") == "增持")
    dec = sum(1 for h in holders if h.get("direction") == "减持")

    result = {
        "symbol": symbol,
        "total": len(holders),
        "aggregate_pct": round(total_pct, 2),
        "increasing": inc,
        "decreasing": dec,
        "holders": holders[:count],
        "note": "aggregate_pct = 列出的机构股东合计持股比例(可能超 100%:含借出股/多重统计)",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 机构股东(共 {len(holders)} 家,合计持股 {result['aggregate_pct']}%)")
    print(f"  增持 {inc} 家 / 减持 {dec} 家 → "
          f"{'机构偏向加仓(偏多)' if inc > dec else ('机构偏向减仓(偏空)' if dec > inc else '多空均衡')}")
    print()
    rows = [{
        "股东": str(h.get("shareholder_name", ""))[:24],
        "持股%": h.get("percent_of_shares", ""),
        "方向": h.get("direction", ""),
        "报告日": h.get("report_date", ""),
        "股东代码": h.get("holder_symbol", ""),
    } for h in holders[:count]]
    print_display_table(rows, columns=["股东", "持股%", "方向", "报告日", "股东代码"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="机构股东列表+变动")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 700.HK")
    parser.add_argument("--count", type=int, default=15, help="显示条数(默认 15)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_shareholders(args.symbol, count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取机构股东", str(e))
        sys.exit(1)
