"""多股估值横向对比(≤5 只;单只时自动对比行业同行)。

对应 Longbridge CLI: compare <SYM> [OTHERS...] --currency
官方 skill 无此加工分析。输出:核心估值/质量指标表 + 同组内排名标注。

指标: 现价/市值/PE/PB/PS/ROE/ROA/净利率/EPS/DPS/股息率/派息率/杠杆/
      资产/负债/营收/净利/换手率/成交量(多币种归一 --currency)

用法:
    python compare_stocks.py AAPL.US MSFT.US NVDA.US            # 指定对比
    python compare_stocks.py AAPL.US                            # vs 行业同行(服务端选)
    python compare_stocks.py 700.HK 9988.HK 3690.HK --currency HKD
    python compare_stocks.py AAPL.US MSFT.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    compare_stocks as compare_stocks_cli,
    counter_id_to_symbol,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)

# 对比维度: (key, 中文名, lower_better=True 表示数值越低越好)
_METRICS = [
    ("pe", "PE", True),
    ("pb", "PB", True),
    ("ps", "PS", True),
    ("roe", "ROE%", False),
    ("roa", "ROA%", False),
    ("net_margin", "净利率%", False),
    ("div_yld", "股息率%", False),
]


def _fmt_cap(v) -> str:
    f = to_float(v)
    if f is None:
        return ""
    if abs(f) >= 1e12:
        return f"{f/1e12:.2f}万亿"
    if abs(f) >= 1e8:
        return f"{f/1e8:.0f}亿"
    return f"{f:.0f}"


def fetch_compare(symbols: list[str], currency: str = "USD",
                  output_json: bool = False) -> dict:
    if len(symbols) > 5:
        raise ValueError("最多对比 5 只(1 基准 + 4 对比)。")
    rows = compare_stocks_cli(symbols, currency=currency)
    if is_empty(rows):
        raise ValueError(f"无对比数据: {', '.join(symbols)}。")

    for r in rows:
        r["symbol"] = counter_id_to_symbol(r.get("counter_id", "")) or r.get("counter_id", "")

    # 同组内排名:第 1 名 = 该维度最优(估值类越低越好,质量类越高越好)
    ranks: dict[str, dict[str, int]] = {}
    for key, label, lower_better in _METRICS:
        vals = [(r.get("symbol"), to_float(r.get(key))) for r in rows]
        vals = [(s, v) for s, v in vals if v is not None]
        for i, (s, _) in enumerate(sorted(vals, key=lambda x: x[1],
                                          reverse=not lower_better)):
            ranks.setdefault(s, {})[key] = i + 1

    def _best(key: str, lower_better: bool) -> str | None:
        pairs = [(r.get("symbol"), to_float(r.get(key))) for r in rows]
        pairs = [(s, v) for s, v in pairs if v is not None]
        if not pairs:
            return None
        return (min if lower_better else max)(pairs, key=lambda x: x[1])[0]

    result = {
        "symbols": symbols,
        "currency": currency,
        "count": len(rows),
        "best_per_metric": {label: _best(key, lb)
                            for key, label, lb in _METRICS},
        "ranks": ranks,
        "rows": rows,
    }

    if output_json:
        print_json(result)
        return result

    mode = "指定对比" if len(symbols) > 1 else "vs 行业同行(服务端选择)"
    print(f"多股估值对比({mode},{len(rows)} 只,币种 {currency})")
    print()
    table = [{
        "symbol": r["symbol"],
        "名称": str(r.get("name", ""))[:10],
        "现价": r.get("price_close", ""),
        "市值": _fmt_cap(r.get("market_value")),
        "PE": round(to_float(r.get("pe")), 1) if to_float(r.get("pe")) is not None else "",
        "PE名次": ranks.get(r["symbol"], {}).get("pe", ""),
        "PB": round(to_float(r.get("pb")), 2) if to_float(r.get("pb")) is not None else "",
        "PS": round(to_float(r.get("ps")), 2) if to_float(r.get("ps")) is not None else "",
        "ROE%": round(to_float(r.get("roe")), 1) if to_float(r.get("roe")) is not None else "",
        "净利率%": round(to_float(r.get("net_margin")), 1) if to_float(r.get("net_margin")) is not None else "",
        "股息率%": round(to_float(r.get("div_yld")), 2) if to_float(r.get("div_yld")) is not None else "",
    } for r in rows]
    print_display_table(table, columns=["symbol", "名称", "现价", "市值", "PE", "PE名次", "PB", "PS",
                                        "ROE%", "净利率%", "股息率%"])
    print("\n★ 各维度最优: " + " / ".join(
        f"{label}={sym or '无数据'}" for (key, label, _), sym in
        zip(_METRICS, result["best_per_metric"].values())))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="多股估值横向对比(≤5只)")
    parser.add_argument("symbols", nargs="+", help="标的代码(1~5 只),如 AAPL.US MSFT.US")
    parser.add_argument("--currency", default="USD", choices=["USD", "HKD", "CNY"],
                        help="归一币种(默认 USD)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_compare(symbols=args.symbols, currency=args.currency, output_json=args.output_json)
    except Exception as e:
        print_error("多股对比", str(e))
        sys.exit(1)
