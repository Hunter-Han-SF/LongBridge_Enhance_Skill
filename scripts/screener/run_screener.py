"""选股器:预设策略执行 / 自定义指标条件筛选 / 指标发现。

对应 Longbridge CLI: screener strategies / run <ID> / filter KEY:MIN:MAX / indicators
这是模块⑩(选股)的入口:从"只能分析给定标的"升级为"能发现标的"。
筛出的股票可直接送 scripts/decision/analyze_buy_sell.py 六维打分。

四种模式:
  1. strategies 模式(默认): 列出预设策略(今日大涨/低估值/高盈利高成长等)
  2. run 模式: 执行某个预设策略 --run 27
  3. filter 模式: 自定义条件 --filter pettm:10:50 --filter roe:5: --market HK
  4. indicators 模式: 列出全部可用筛选指标(key/名称/范围)

常用指标 key(实测):
  marketcap(市值) pettm pbmrq roe roa netmargin epsttm salesgrowthyoy
  netincomegrowthyoy epsgrowthyoy divyld(股息率) leverage(杠杆) bpsgrowthyoy
  assets sales netincome asset_turnover fiveyearavgdps dpseps

条件语法: KEY:MIN:MAX(MIN/MAX 可省略一侧,如 roe:5: 表示 ROE≥5)

用法:
    python run_screener.py                                  # 预设策略列表
    python run_screener.py --run 27                         # 执行"低估值"
    python run_screener.py --filter pettm:10:50 --filter roe:5: --market HK
    python run_screener.py --indicators                     # 可用指标
    python run_screener.py --filter divyld:4: --market US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_screener_indicators,
    get_screener_strategies,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    run_screener_strategy,
    screener_filter,
    to_float,
)


def _fmt_cap(v) -> str:
    f = to_float(v)
    if f is None or f == "":
        return str(v or "")
    if abs(f) >= 1e12:
        return f"{f/1e12:.2f}万亿"
    if abs(f) >= 1e8:
        return f"{f/1e8:.2f}亿"
    if abs(f) >= 1e4:
        return f"{f/1e4:.2f}万"
    return f"{f:.2f}"


def _print_stocks(items: list[dict], market: str, note: str) -> None:
    print(f"筛选结果({market},{len(items)} 只) — {note}")
    print()
    rows = [{
        "symbol": it.get("symbol", ""),
        "名称": str(it.get("name", ""))[:14],
        "行业": str(it.get("industry", ""))[:10],
        "市值": _fmt_cap(it.get("marketcap")),
        "PE(TTM)": round(to_float(it.get("pettm")), 1) if to_float(it.get("pettm")) is not None else "",
        "PB": round(to_float(it.get("pbmrq")), 2) if to_float(it.get("pbmrq")) is not None else "",
        "涨跌%": round(to_float(it.get("prevchg")), 2) if to_float(it.get("prevchg")) is not None else "",
        "现价": it.get("prevclose", ""),
    } for it in items]
    print_display_table(rows, columns=["symbol", "名称", "行业", "市值", "PE(TTM)", "PB", "涨跌%", "现价"])


def _strategies_mode(output_json: bool) -> dict:
    strategies = get_screener_strategies()
    if is_empty(strategies):
        raise ValueError("无预设策略数据。")
    result = {"mode": "strategies", "count": len(strategies), "strategies": strategies}
    if output_json:
        print_json(result)
        return result
    print(f"预设选股策略(共 {len(strategies)} 个,--run <ID> 执行)")
    print()
    print_display_table(strategies, columns=["id", "name", "type"])
    return result


def _run_mode(strategy_id: int, output_json: bool) -> dict:
    items = run_screener_strategy(strategy_id)
    strategies = get_screener_strategies()
    name = next((s.get("name") for s in strategies if to_float(s.get("id")) == strategy_id), "")
    if is_empty(items):
        raise ValueError(f"策略 {strategy_id}{f'({name})' if name else ''} 无结果。")
    result = {"mode": "run", "strategy_id": strategy_id, "strategy_name": name,
              "count": len(items), "items": items}
    if output_json:
        print_json(result)
        return result
    _print_stocks(items, "ALL", f"策略 {strategy_id} {name}")
    return result


def _filter_mode(conditions: list[str], market: str, output_json: bool) -> dict:
    for cond in conditions:
        if len(cond.split(":")) < 2 or not cond.split(":")[0]:
            raise ValueError(f"条件格式错误: {cond!r}(应为 KEY:MIN:MAX,如 pettm:10:50 或 roe:5:)")
    items = screener_filter(conditions, market=market)
    if is_empty(items):
        raise ValueError(f"无符合条件的股票(条件: {' '.join(conditions)}, 市场 {market})。"
                         f"可用 --indicators 查 key 与取值范围。")
    result = {"mode": "filter", "market": market, "conditions": conditions,
              "count": len(items), "items": items}
    if output_json:
        print_json(result)
        return result
    _print_stocks(items, market, " ".join(conditions))
    return result


def _indicators_mode(output_json: bool) -> dict:
    indicators = get_screener_indicators()
    if is_empty(indicators):
        raise ValueError("无指标数据。")
    result = {"mode": "indicators", "count": len(indicators), "indicators": indicators}
    if output_json:
        print_json(result)
        return result
    print(f"可用筛选指标(共 {len(indicators)} 个,条件语法 KEY:MIN:MAX)")
    print()
    rows = [{
        "key": i.get("key", ""),
        "名称": i.get("name", ""),
        "单位": i.get("unit", ""),
        "min": i.get("min") if i.get("min") is not None else "",
        "max": i.get("max") if i.get("max") is not None else "",
    } for i in indicators]
    print_display_table(rows, columns=["key", "名称", "单位", "min", "max"])
    return result


def fetch_screener(
    run: int | None = None,
    conditions: list[str] | None = None,
    market: str = "HK",
    indicators: bool = False,
    output_json: bool = False,
) -> dict:
    if indicators:
        return _indicators_mode(output_json)
    if run is not None:
        return _run_mode(run, output_json)
    if conditions:
        return _filter_mode(conditions, market, output_json)
    return _strategies_mode(output_json)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="选股器(预设策略/自定义条件)")
    parser.add_argument("--run", type=int, default=None, help="执行预设策略的 ID(先用默认模式查看)")
    parser.add_argument("--filter", dest="conditions", action="append", default=None,
                        help="筛选条件 KEY:MIN:MAX,可多次传递,如 --filter pettm:10:50 --filter roe:5:")
    parser.add_argument("--market", default="HK", choices=["HK", "US", "CN", "SG"],
                        help="filter 模式的市场(默认 HK)")
    parser.add_argument("--indicators", action="store_true", help="列出全部可用筛选指标")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_screener(run=args.run, conditions=args.conditions, market=args.market,
                       indicators=args.indicators, output_json=args.output_json)
    except Exception as e:
        print_error("选股筛选", str(e))
        sys.exit(1)
