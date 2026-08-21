"""获取业务分部营收拆分(地区/产品维度)+ 集中度分析。

对应 Longbridge CLI: business-segments <SYMBOL>
官方 skill 无此加工分析。加工:各分部占比/同比 + 集中度(CR1/CR2)。

用法:
    python get_business_segments.py AAPL.US
    python get_business_segments.py 700.HK
    python get_business_segments.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_business_segments,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _fmt_value(v) -> str:
    f = to_float(v)
    if f is None:
        return ""
    if abs(f) >= 1e12:
        return f"{f/1e12:.2f}万亿"
    if abs(f) >= 1e8:
        return f"{f/1e8:.1f}亿"
    if abs(f) >= 1e4:
        return f"{f/1e4:.1f}万"
    return f"{f:.2f}"


def fetch_business_segments(symbol: str, output_json: bool = False) -> dict:
    segments = get_business_segments(symbol)
    if is_empty(segments):
        raise ValueError(f"无业务分部数据({symbol})。部分小票/新股无此数据。")

    total_value = sum(to_float(s.get("value")) or 0 for s in segments)
    percents = sorted([to_float(s.get("percent")) or 0 for s in segments], reverse=True)
    result = {
        "symbol": symbol,
        "count": len(segments),
        "total_value": total_value,
        "cr1": round(percents[0], 2) if percents else None,
        "cr2": round(sum(percents[:2]), 2) if len(percents) >= 2 else None,
        "segments": segments,
        "note": "CR1/CR2 = 第一/前二大分部营收占比(集中度风险,>70% 单一依赖)",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 业务分部营收拆分({len(segments)} 个分部,合计 {_fmt_value(total_value)})")
    print(f"  集中度: CR1={result['cr1']}% / CR2={result['cr2']}%")
    print()
    rows = [{
        "分部": s.get("name", ""),
        "营收": _fmt_value(s.get("value")),
        "占比%": s.get("percent", ""),
        "同比%": round(to_float(s.get("yoy")), 2) if to_float(s.get("yoy")) is not None else "",
    } for s in segments]
    print_display_table(rows, columns=["分部", "营收", "占比%", "同比%"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="业务分部营收拆分+集中度")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 700.HK")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_business_segments(args.symbol, output_json=args.output_json)
    except Exception as e:
        print_error("获取业务分部", str(e))
        sys.exit(1)
