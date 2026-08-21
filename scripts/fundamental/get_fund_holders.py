"""获取持有该股票的基金/ETF(机构持有面)。

对应 Longbridge CLI: fund-holder <SYMBOL>
含义:哪些基金/ETF 把该股票列为重仓(position_ratio = 该股票占基金净值 %)。
高 position_ratio 的基金对该股的申赎会放大股价波动。

用法:
    python get_fund_holders.py AAPL.US
    python get_fund_holders.py AAPL.US --count 10
    python get_fund_holders.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    counter_id_to_symbol,
    get_fund_holders,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def fetch_fund_holders(symbol: str, count: int = 15, output_json: bool = False) -> dict:
    holders = get_fund_holders(symbol)
    if is_empty(holders):
        raise ValueError(f"无基金持仓数据({symbol})。小票/新股常无覆盖。")

    holders.sort(key=lambda h: to_float(h.get("position_ratio")) or 0, reverse=True)
    result = {
        "symbol": symbol,
        "total": len(holders),
        "top": holders[:count],
        "note": "position_ratio = 该股票占基金净值的百分比,越高则基金申赎对股价影响越大",
    }

    if output_json:
        print_json(result)
        return result

    print(f"持有 {symbol} 的基金/ETF(共 {len(holders)} 家,按占基金净值比例排序)")
    print()
    rows = [{
        "symbol": counter_id_to_symbol(h.get("counter_id", "")) or h.get("code", ""),
        "名称": str(h.get("name", ""))[:32],
        "占净值%": round(to_float(h.get("position_ratio")), 2)
            if to_float(h.get("position_ratio")) is not None else "",
        "报告日": h.get("report_date", ""),
        "币种": h.get("currency", ""),
    } for h in holders[:count]]
    print_display_table(rows, columns=["symbol", "名称", "占净值%", "报告日", "币种"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="基金/ETF 持仓(谁重仓这只股)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US")
    parser.add_argument("--count", type=int, default=15, help="显示条数(默认 15)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_fund_holders(args.symbol, count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取基金持仓", str(e))
        sys.exit(1)
