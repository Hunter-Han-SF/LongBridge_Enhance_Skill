"""获取大中小单资金流向(大/中/小单分布 + 分钟级净流入时序)。

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


def _fmt_money(v, unit_verified: bool) -> str:
    """金额可读化: 万 / 亿。"""
    f = to_float(v)
    if f is None:
        return "N/A"
    if not unit_verified:
        amount = f"{f:.6g}" if 0 < abs(f) < 0.01 else f"{f:,.2f}"
        return f"{amount}（来源单位）"
    a = abs(f)
    if a >= 1e8:
        return f"{f/1e8:.2f}亿"
    if a >= 1e4:
        return f"{f/1e4:.2f}万"
    return f"{f:.2f}"


def _direction_label(net_large: float | None) -> str:
    """根据大单净额描述资金方向。"""
    if net_large is None:
        return "大单方向资料不足"
    if net_large > 0:
        return "大单净流入 🟢"
    if net_large < 0:
        return "大单净流出 🔴"
    return "大单持平 ⚪"


def _ts_to_hm(ts) -> str:
    """ISO 时间戳 → HH:MM。"""
    if not ts:
        return ""
    try:
        # 形如 2026-08-07T13:30:00Z
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%H:%M")
    except (ValueError, TypeError):
        return str(ts)


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

    net = snap.get("net") or {}
    cap_in = snap.get("capital_in") or {}
    cap_out = snap.get("capital_out") or {}
    net_large = to_float(net.get("large"))
    unit_verified = snap.get("unit_verified", False)

    result = {
        "symbol": symbol,
        "timestamp": snap.get("timestamp"),
        "mode": "snapshot",
        "capital_in": cap_in,
        "capital_out": cap_out,
        "net": net,
        "direction": _direction_label(net_large),
        "amount_unit": snap.get("amount_unit", "source_unit"),
        "unit_verified": unit_verified,
        "unit_note": snap.get("unit_note"),
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 当日资金流向(快照,{snap.get('timestamp','')})")
    print(f"  {_direction_label(net_large)}")
    if result["unit_note"]:
        print(f"  {result['unit_note']}")
    print()
    labels = {"large": "大单", "medium": "中单", "small": "小单"}
    rows = [{
        "类型": label,
        "流入": _fmt_money(cap_in.get(size), unit_verified),
        "流出": _fmt_money(cap_out.get(size), unit_verified),
        "净额": _fmt_money(net.get(size), unit_verified),
    } for size, label in labels.items()]
    totals = []
    for side in (cap_in, cap_out):
        amounts = [to_float(side.get(size)) for size in labels]
        totals.append(sum(amounts) if all(v is not None for v in amounts) else None)
    rows.append({
        "类型": "合计",
        "流入": _fmt_money(totals[0], unit_verified),
        "流出": _fmt_money(totals[1], unit_verified),
        "净额": _fmt_money(net.get("total"), unit_verified),
    })
    print_display_table(rows, columns=["类型", "流入", "流出", "净额"])
    return result


def _flow_mode(symbol: str, output_json: bool) -> dict:
    series = get_capital_flow_series(symbol)
    if is_empty(series):
        raise ValueError(f"无分钟资金流数据。确认 {symbol} 当日有交易。")

    last = series[-1]
    flow_mode = last.get("flow_mode", "unknown")
    unit_verified = last.get("unit_verified", False)
    deltas = []
    for row in series:
        row["time_str"] = _ts_to_hm(row.get("time") or row.get("timestamp"))
        row["raw_fmt"] = _fmt_money(row.get("inflow"), unit_verified)
        delta = to_float(row.get("minute_delta")) if flow_mode != "unknown" else None
        row["delta_fmt"] = _fmt_money(delta, unit_verified)
        row["cum_fmt"] = _fmt_money(row.get("cumulative_inflow"), unit_verified)
        if delta is not None:
            deltas.append((delta, row["time_str"]))

    def extreme(points, choose):
        if not points:
            return None
        delta, time = choose(points, key=lambda point: point[0])
        return {"time": time, "minute_delta": delta}

    result = {
        "symbol": symbol,
        "mode": "flow",
        "flow_mode": flow_mode,
        "amount_unit": last.get("amount_unit", "source_unit"),
        "unit_verified": unit_verified,
        "points": len(series),
        "final_cumulative": last.get("cumulative_inflow") if flow_mode == "cumulative" else None,
        "observed_sum": last.get("observed_sum") if flow_mode == "incremental" else None,
        "peak_inflow": extreme([p for p in deltas if p[0] > 0], max),
        "max_outflow": extreme([p for p in deltas if p[0] < 0], min),
        "series": series,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 日内资金流({len(series)} 个点)")
    if flow_mode == "unknown":
        print("  来源序列口径未核实，仅展示来源值。")
    elif flow_mode == "cumulative":
        print(f"  当日累计净流入: {_fmt_money(result['final_cumulative'], unit_verified)}")
    else:
        print(f"  已返回样本净流入合计: {_fmt_money(result['observed_sum'], unit_verified)}")
    for key, label in (("peak_inflow", "最大流入"), ("max_outflow", "最大流出")):
        peak = result[key]
        if peak is not None:
            print(f"  {label}: {peak['time']} {_fmt_money(peak['minute_delta'], unit_verified)}")
    print()
    columns = {"unknown": ["time_str", "raw_fmt"],
               "cumulative": ["time_str", "delta_fmt", "cum_fmt"],
               "incremental": ["time_str", "delta_fmt"]}
    print_display_table(_sample_series(series), columns=columns[flow_mode])
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
    parser = argparse.ArgumentParser(description="大中小单资金流向(大中小单分布/分钟流)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 700.HK")
    parser.add_argument("--flow", action="store_true", help="分钟级资金流时序(默认快照)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_capital_flow(args.symbol, flow=args.flow, output_json=args.output_json)
    except Exception as e:
        print_error("获取资金流", str(e))
        sys.exit(1)
