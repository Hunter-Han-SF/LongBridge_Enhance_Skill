"""获取公司行动事件流(分红/拆合股/配股/回购公告等)。

对应 Longbridge CLI: corp-action <SYMBOL>
与 get_dividend_calendar.py(全市场日历)互补:本脚本按标的聚合全部公司行动。

用法:
    python get_corp_actions.py AAPL.US
    python get_corp_actions.py AAPL.US --count 10
    python get_corp_actions.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_corp_actions,
    is_empty,
    print_display_table,
    print_error,
    print_json,
)


def fetch_corp_actions(symbol: str, count: int = 20, output_json: bool = False) -> dict:
    items = get_corp_actions(symbol)
    if is_empty(items):
        raise ValueError(f"无公司行动数据({symbol})。")

    type_counter = Counter(str(i.get("act_type", "")) for i in items)
    result = {
        "symbol": symbol,
        "total": len(items),
        "type_distribution": dict(type_counter),
        "items": items[:count],
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 公司行动(共 {len(items)} 条)")
    print("  类型分布: " + " / ".join(f"{t}{c}条" for t, c in type_counter.items()))
    print()
    rows = [{
        "日期": f"{str(i.get('date', ''))[:4]}-{str(i.get('date', ''))[4:6]}-{str(i.get('date', ''))[6:8]}",
        "类型": i.get("act_type", ""),
        "事件": i.get("date_type", ""),
        "内容": str(i.get("act_desc", ""))[:24],
    } for i in items[:count]]
    print_display_table(rows, columns=["日期", "类型", "事件", "内容"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="公司行动事件流")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US")
    parser.add_argument("--count", type=int, default=20, help="显示条数(默认 20)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_corp_actions(args.symbol, count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取公司行动", str(e))
        sys.exit(1)
