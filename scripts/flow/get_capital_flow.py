"""获取主力资金流向(大/中/小单分布 + 分钟级净流入时序)。

对应 Longbridge CLI: capital <SYMBOL> / capital <SYMBOL> --flow
官方 skill 无此加工分析。

两种模式:
  1. 快照模式(默认): 当日大单/中单/小单的流入、流出、净额,判断主力方向
  2. 时序模式(--flow): 当日分钟级资金净流入,看主力何时进场/离场

资金分布含义:
  - large(大单): 机构/主力,通常单笔金额大
  - medium(中单): 大户
  - small(小单): 散户
  - 主力净流入 = 大单净额,正=主力买入,负=主力卖出

用法:
    python get_capital_flow.py AAPL.US              # 快照
    python get_capital_flow.py AAPL.US --flow       # 分钟流时序
    python get_capital_flow.py 700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_capital_flow_series,
    get_capital_flow_snapshot,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _fmt_money(v) -> str:
    """金额可读化: 万 / 亿。"""
    f = to_float(v)
    if f is None:
        return str(v)
    a = abs(f)
    if a >= 1e8:
        return f"{f/1e8:.2f}亿"
    if a >= 1e4:
        return f"{f/1e4:.2f}万"
    return f"{f:.2f}"


def _direction_label(net_large: float) -> str:
    """根据大单净额判断主力方向。"""
    if net_large > 0:
        return "主力净流入 🟢(机构买入)"
    if net_large < 0:
        return "主力净流出 🔴(机构卖出)"
    return "主力持平 ⚪"


def _ts_to_hm(ts) -> str:
    """ISO 时间戳 → HH:MM。"""
    if not ts:
        return ""
    try:
        # 形如 2026-08-07T13:30:00Z
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M")
    except (ValueError, TypeError):
        return str(ts)[:5]


def fetch_capital_flow(
    symbol: str,
    flow: bool = False,
    output_json: bool = False,
) -> dict:
    if flow:
        return _flow_mode(symbol, output_json)
    return _snapshot_mode(symbol, output_json)


def _snapshot_mode(symbol: str, output_json: bool) -> dict:
    snap = get_capital_flow_snapshot(symbol)
    if is_empty(snap):
        raise ValueError(f"无资金流数据。确认 {symbol} 是当日有交易的活跃标的。")

    net = snap.get("net", {})
    cap_in = snap.get("capital_in", {})
    cap_out = snap.get("capital_out", {})
    net_large = to_float(net.get("large"), 0) or 0

    result = {
        "symbol": symbol,
        "timestamp": snap.get("timestamp"),
        "mode": "snapshot",
        "capital_in": cap_in,
        "capital_out": cap_out,
        "net": net,
        "direction": _direction_label(net_large),
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 当日资金流向(快照,{snap.get('timestamp','')})")
    print(f"  主力方向: {_direction_label(net_large)}")
    print()
    # 分布表:流入/流出/净额并排
    rows = []
    for size, label in [("large", "大单"), ("medium", "中单"), ("small", "小单")]:
        rows.append({
            "类型": label,
            "流入": _fmt_money((cap_in or {}).get(size)),
            "流出": _fmt_money((cap_out or {}).get(size)),
            "净额": _fmt_money(net.get(size)),
        })
    rows.append({
        "类型": "合计",
        "流入": _fmt_money(sum(to_float((cap_in or {}).get(s), 0) or 0 for s in ("large", "medium", "small"))),
        "流出": _fmt_money(sum(to_float((cap_out or {}).get(s), 0) or 0 for s in ("large", "medium", "small"))),
        "净额": _fmt_money(net.get("total")),
    })
    print_display_table(rows, columns=["类型", "流入", "流出", "净额"])
    return result


def _flow_mode(symbol: str, output_json: bool) -> dict:
    series = get_capital_flow_series(symbol)
    if is_empty(series):
        raise ValueError(f"无分钟资金流数据。确认 {symbol} 当日有交易。")

    # 加工:累计净流入 + 可读时间
    cumulative = 0.0
    for row in series:
        inflow = to_float(row.get("inflow"), 0) or 0
        cumulative += inflow
        row["cumulative"] = round(cumulative, 2)
        row["time_str"] = _ts_to_hm(row.get("time"))
        row["inflow_fmt"] = _fmt_money(inflow)
        row["cumulative_fmt"] = _fmt_money(cumulative)

    # 找峰值(最大单分钟流入/流出)
    peak = max(series, key=lambda r: to_float(r.get("inflow"), 0) or 0)
    trough = min(series, key=lambda r: to_float(r.get("inflow"), 0) or 0)

    result = {
        "symbol": symbol,
        "mode": "flow",
        "points": len(series),
        "final_cumulative": series[-1]["cumulative"],
        "peak_inflow": {"time": peak["time_str"], "value": peak["inflow"]},
        "max_outflow": {"time": trough["time_str"], "value": trough["inflow"]},
        "series": series,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 当日分钟资金净流入({len(series)} 个点)")
    print(f"  累计净流入: {_fmt_money(series[-1]['cumulative'])}")
    print(f"  最大单分钟流入: {peak['time_str']} {_fmt_money(peak['inflow'])}")
    print(f"  最大单分钟流出: {trough['time_str']} {_fmt_money(trough['inflow'])}")
    print()
    # 只显示关键节点(每 30 分钟采样 + 首5分钟)
    sampled = _sample_series(series)
    print_display_table(sampled, columns=["time_str", "inflow_fmt", "cumulative_fmt"])
    return result


def _sample_series(series: list[dict]) -> list[dict]:
    """长序列采样显示:前5分钟 + 之后每30分钟取一个 + 最后一个。"""
    if len(series) <= 20:
        return series
    out = series[:5]
    for i in range(5, len(series) - 1, 30):
        out.append(series[i])
    if series[-1] not in out:
        out.append(series[-1])
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="主力资金流向(大中小单分布/分钟流)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 700.HK")
    parser.add_argument("--flow", action="store_true", help="分钟级资金流时序(默认快照)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_capital_flow(args.symbol, flow=args.flow, output_json=args.output_json)
    except Exception as e:
        print_error("获取资金流", str(e))
        sys.exit(1)
