"""获取港股经营回顾与财务指标(按报告期)。

对应 Longbridge CLI: operating <SYMBOL>
⚠️ 仅港股。内容:营业收入/净利润/毛利/经营现金流等指标 + 同比。

用法:
    python get_operating.py 700.HK
    python get_operating.py 700.HK --count 2
    python get_operating.py 700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_operating,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def fetch_operating(symbol: str, count: int = 2, output_json: bool = False) -> dict:
    periods = get_operating(symbol)
    if is_empty(periods):
        raise ValueError(f"无经营回顾数据({symbol})。确认是港股(仅 HK 支持 operating)。")

    result = {
        "symbol": symbol,
        "total_periods": len(periods),
        "periods": [],
    }

    for p in periods[:count]:
        fin = p.get("financial") or {}
        indicators = fin.get("indicators", [])
        period_label = p.get("period") or p.get("report_period") or ""
        result["periods"].append({
            "period": period_label,
            "currency": fin.get("currency"),
            "indicators": indicators,
            "raw": {k: v for k, v in p.items() if k != "financial"},
        })

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 经营回顾(共 {len(periods)} 个报告期,仅港股)")
    print()
    for p in result["periods"]:
        print(f"📅 {p['period'] or '(最新)'}(币种 {p['currency']})")
        rows = [{
            "指标": i.get("indicator_name", ""),
            "数值": i.get("indicator_value", ""),
            "同比%": round(to_float(i.get("yoy")), 2)
                if to_float(i.get("yoy")) is not None else "",
        } for i in p["indicators"]]
        if rows:
            print_display_table(rows, columns=["指标", "数值", "同比%"])
        print()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="港股经营回顾(仅HK)")
    parser.add_argument("symbol", help="港股代码,如 700.HK")
    parser.add_argument("--count", type=int, default=2, help="显示报告期数(默认 2)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_operating(args.symbol, count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取经营回顾", str(e))
        sys.exit(1)
