"""获取财务共识明细(按报告期的营收/EPS 等预测 vs 实际,含超/逊预期判断)。

对应 Longbridge CLI: consensus <SYMBOL>
与 get_analyst_consensus.py(评级/目标价/EPS 预测)互补:本脚本是科目级共识。

每个报告期含 details[]: 营业收入/净利润/EPS 等科目的 estimate/actual/is_released。
加工: 已公布期计算实际 vs 预测的偏离(beat/miss 幅度)。

用法:
    python get_consensus.py AAPL.US
    python get_consensus.py AAPL.US --count 4
    python get_consensus.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_consensus,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _fmt_bignum(v) -> str:
    f = to_float(v)
    if f is None:
        return ""
    if abs(f) >= 1e12:
        return f"{f/1e12:.2f}万亿"
    if abs(f) >= 1e8:
        return f"{f/1e8:.1f}亿"
    return f"{f:.2f}"


def _beat_miss(estimate, actual) -> tuple[str, str]:
    e, a = to_float(estimate), to_float(actual)
    if a is None or a == "":
        return "待公布", ""
    if e is None or e == "":
        return "已公布", ""
    pct = (a - e) / abs(e) * 100 if e else 0
    if pct > 0.5:
        return "超预期", f"+{pct:.1f}%"
    if pct < -0.5:
        return "逊预期", f"{pct:.1f}%"
    return "符合", f"{pct:+.1f}%"


def fetch_consensus(symbol: str, count: int = 6, output_json: bool = False) -> dict:
    data = get_consensus(symbol)
    periods = data.get("list", [])
    if is_empty(periods):
        raise ValueError(f"无共识数据({symbol})。小票/新股常无覆盖。")

    for p in periods[:count]:
        for d in p.get("details", []):
            verdict, pct = _beat_miss(d.get("estimate"), d.get("actual"))
            d["verdict"] = verdict
            d["vs_estimate_pct"] = pct

    def _period_label(p: dict) -> str:
        return (p.get("period_text")
                or (f"Q{p.get('fiscal_period')} {p.get('fiscal_year')}"
                    if p.get("fiscal_year") else "") or "")

    result = {
        "symbol": symbol,
        "currency": data.get("currency"),
        "current_period": data.get("current_period"),
        "total_periods": len(periods),
        "periods": periods[:count],
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 财务共识明细(币种 {data.get('currency')},共 {len(periods)} 个报告期)")
    print()
    for p in periods[:count]:
        print(f"📅 {_period_label(p)}")
        rows = [{
            "科目": d.get("name", ""),
            "预测": _fmt_bignum(d.get("estimate")),
            "实际": _fmt_bignum(d.get("actual")),
            "结果": d.get("verdict", ""),
            "偏离": d.get("vs_estimate_pct", ""),
        } for d in p.get("details", [])]
        if rows:
            print_display_table(rows, columns=["科目", "预测", "实际", "结果", "偏离"])
        print()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="财务共识明细(预测vs实际)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US")
    parser.add_argument("--count", type=int, default=6, help="显示报告期数(默认 6)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_consensus(args.symbol, count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取财务共识", str(e))
        sys.exit(1)
