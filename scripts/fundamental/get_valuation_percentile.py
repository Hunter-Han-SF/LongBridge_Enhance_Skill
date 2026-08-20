"""估值分位分析(当前估值 vs 5 年历史 + 行业同行)。

数据源: longbridge valuation(实测返回 overview/history/peers 三块)。
回答"现在贵不贵":
  - 当前 PE/PB 处于近 5 年历史的百分位(便宜 = 低分位)
  - 与行业同行/中位数对比
  - 历史区间(最高/中位/最低)

估值分位解读:
  < 30%  历史低位(便宜区间)
  30-70% 合理区间
  > 70%  历史高位(偏贵)

用法:
    python get_valuation_percentile.py AAPL.US
    python get_valuation_percentile.py 0700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    counter_id_to_symbol,
    get_valuation,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _pctl_label(p: float | None) -> str:
    if p is None:
        return ""
    if p < 30:
        return "🟢 历史低位(便宜区间)"
    if p <= 70:
        return "⚪ 合理区间"
    return "🔴 历史高位(偏贵)"


def _percentile_of(series: list[float], current: float) -> float:
    if not series:
        return 50.0
    below = sum(1 for v in series if v < current)
    return below / len(series) * 100


def analyze(symbol: str, output_json: bool = False, quiet: bool = False) -> dict:
    data = get_valuation(symbol)
    if not data:
        raise ValueError(f"无 {symbol} 估值数据")

    # 1. 历史:各 metric 的当前值/分位/区间
    metrics_out = []
    hist = ((data.get("history") or {}).get("metrics")) or {}
    overview_metrics = ((data.get("overview") or {}).get("metrics")) or {}
    for name, m in hist.items():
        series = [to_float(p.get("value")) for p in (m.get("list") or [])]
        series = [v for v in series if v and v > 0]
        current = to_float(m.get("circle"))
        if current is None and series:
            current = series[-1]
        if not series or current is None:
            continue
        pctl = _percentile_of(series, current)
        metrics_out.append({
            "metric": name.upper(),
            "current": current,
            "hist_high": max(series),
            "hist_median": to_float(m.get("median")) or sorted(series)[len(series) // 2],
            "hist_low": min(series),
            "history_points": len(series),
            "percentile": round(pctl, 1),
            "label": _pctl_label(pctl),
        })

    if not metrics_out:
        raise ValueError(f"{symbol} 无可用估值历史序列(valuation.history.metrics 为空)")

    # 2. 同行对比(第一可用 metric)
    peers = (data.get("peers") or {}).get(metrics_out[0]["metric"].lower()) or {}
    peer_rows = []
    for p in (peers.get("list") or []):
        peer_rows.append({
            "symbol": counter_id_to_symbol(p.get("counter_id", "")) or p.get("counter_id", ""),
            "name": p.get("name", ""),
            "value": to_float(p.get("value")),
            "is_target": p.get("counter_id", "").upper().endswith(symbol.split(".")[0].upper()),
        })
    # 目标在同行中的排名
    target_rank = None
    for i, r in enumerate(peer_rows, 1):
        if r["is_target"]:
            target_rank = i
            break

    # 综合:取第一 metric(通常 PE)作为主结论
    main = metrics_out[0]
    result = {
        "symbol": symbol,
        "metrics": metrics_out,
        "peers": {"metric": main["metric"], "industry_median": to_float(peers.get("industry_median")),
                  "target_rank": target_rank, "total_peers": len(peer_rows), "list": peer_rows},
        "main": {"metric": main["metric"], "current": main["current"],
                 "percentile": main["percentile"], "verdict": main["label"]},
        "note": "分位基于 valuation 历史(约5年)序列;越低越便宜。同行对比来自 peers 字段。",
    }

    if output_json:
        print_json(result)
        return result
    if quiet:
        return result

    print(f"{symbol} 估值分位")
    for m in metrics_out:
        print(f"  {m['metric']}: 当前 {m['current']:.2f} | 历史低 {m['hist_low']:.2f} / "
              f"中位 {m['hist_median']:.2f} / 高 {m['hist_high']:.2f}({m['history_points']} 点)")
        print(f"    → 当前处于历史 {m['percentile']}% 分位  {m['label']}")
    if peer_rows:
        print()
        print(f"同行对比({main['metric']},行业中位数 {result['peers']['industry_median']}):")
        rows = [{"同行": ("→ " if r["is_target"] else "") + f"{r['symbol']}",
                 "名称": r["name"], "值": r["value"]} for r in peer_rows]
        print_display_table(rows, columns=["同行", "名称", "值"])
        if target_rank:
            print(f"  {symbol.split('.')[0]} 在同行中排第 {target_rank}/{len(peer_rows)}(按估值从高到低)")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="估值分位(当前 vs 5年历史 + 同行)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, output_json=args.output_json)
    except Exception as e:
        print_error("估值分位", str(e))
        sys.exit(1)
