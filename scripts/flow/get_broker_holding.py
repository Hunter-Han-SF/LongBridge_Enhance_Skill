"""获取港股经纪商(投行/券商)持仓变动。

对应 Longbridge CLI: broker-holding <SYMBOL> / detail / daily --broker
⚠️ 仅港股。这是港股特色数据(富途无),反映机构在哪个经纪商手里加减仓。

三种模式:
  1. top 模式(默认): 近 N 日买入/卖出最多的 top10 经纪商
     --period rct_1/rct_5/rct_20/rct_60 (近1/5/20/60日)
  2. detail 模式: 全部经纪商持仓比例 + 各周期变动
  3. daily 模式: 单个经纪商的历史持仓曲线 --broker <ID>

经纪商常见含义:
  - 摩根士丹利/高盛/瑞银: 外资投行,反映外资态度
  - 港股通(深)/港股通(沪): 南向资金(内资)
  - 汇丰/花旗: 托管行,常代表长线机构

用法:
    python get_broker_holding.py 700.HK                       # top 买卖(近1日)
    python get_broker_holding.py 700.HK --period rct_20       # 近20日
    python get_broker_holding.py 700.HK --detail              # 全量明细
    python get_broker_holding.py 700.HK --daily --broker B01274  # 单经纪商历史
    python get_broker_holding.py 700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_broker_holding_detail,
    get_broker_holding_top,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _fmt_shares(v) -> str:
    """股数可读化: 万股 / 亿股。"""
    f = to_float(v)
    if f is None:
        return str(v)
    a = abs(f)
    if a >= 1e8:
        return f"{f/1e8:.2f}亿股"
    if a >= 1e4:
        return f"{f/1e4:.2f}万股"
    return f"{f:.0f}股"


def _fmt_signed(v) -> str:
    """带符号的股数(增减用)。"""
    f = to_float(v)
    if f is None:
        return str(v)
    sign = "+" if f > 0 else ""
    return sign + _fmt_shares(f)


def fetch_broker_holding(
    symbol: str,
    period: str = "rct_1",
    detail: bool = False,
    daily: bool = False,
    broker: str | None = None,
    output_json: bool = False,
) -> dict:
    if daily:
        if not broker:
            raise ValueError("daily 模式必须提供 --broker <经纪商ID>(先用 --detail 或 top 模式查 parti_number)")
        return _daily_mode(symbol, broker, output_json)
    if detail:
        return _detail_mode(symbol, output_json)
    return _top_mode(symbol, period, output_json)


def _top_mode(symbol: str, period: str, output_json: bool) -> dict:
    data = get_broker_holding_top(symbol, period=period)
    if is_empty(data["buy"]) and is_empty(data["sell"]):
        raise ValueError(f"无经纪商数据。确认 {symbol} 是港股(HK),非港股不支持。")

    period_label = {"rct_1": "近1日", "rct_5": "近5日",
                    "rct_20": "近20日", "rct_60": "近60日"}.get(period, period)
    result = {
        "symbol": symbol,
        "mode": "top",
        "period": period,
        "period_label": period_label,
        "updated_at": data["updated_at"],
        "buy": data["buy"],
        "sell": data["sell"],
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 港股经纪商 top10 买卖({period_label},更新 {data['updated_at']})")
    print()
    print("🟢 买入最多(净增持):")
    buy_rows = [{
        "经纪商": b.get("name", ""), "ID": b.get("parti_number", ""),
        "增持股数": _fmt_signed(b.get("chg")),
    } for b in data["buy"][:10]]
    print_display_table(buy_rows, columns=["经纪商", "ID", "增持股数"])
    print()
    print("🔴 卖出最多(净减持):")
    sell_rows = [{
        "经纪商": s.get("name", ""), "ID": s.get("parti_number", ""),
        "减持股数": _fmt_signed(s.get("chg")),
    } for s in data["sell"][:10]]
    print_display_table(sell_rows, columns=["经纪商", "ID", "减持股数"])
    return result


def _detail_mode(symbol: str, output_json: bool) -> dict:
    data = get_broker_holding_detail(symbol)
    brokers = data["list"]
    if is_empty(brokers):
        raise ValueError(f"无明细数据。确认 {symbol} 是港股。")

    result = {
        "symbol": symbol,
        "mode": "detail",
        "updated_at": data["updated_at"],
        "brokers": brokers,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 经纪商全量持仓明细(更新 {data['updated_at']})")
    print(f"共 {len(brokers)} 家经纪商")
    print()
    rows = []
    for b in brokers:
        ratio = b.get("ratio") or {}
        rows.append({
            "经纪商": b.get("name", ""),
            "ID": b.get("parti_number", ""),
            "持仓占比%": ratio.get("value", ""),
            "近1日%": ratio.get("chg_1", ""),
            "近5日%": ratio.get("chg_5", ""),
            "近20日%": ratio.get("chg_20", ""),
            "近60日%": ratio.get("chg_60", ""),
        })
    print_display_table(rows, columns=["经纪商", "ID", "持仓占比%", "近1日%", "近5日%", "近20日%", "近60日%"])
    print("\n提示: 用 --daily --broker <ID> 查看某经纪商的历史持仓曲线")
    return result


def _daily_mode(symbol: str, broker: str, output_json: bool) -> dict:
    from common import run_cli  # noqa: E402
    data = run_cli("broker-holding", "daily", symbol, "--broker", broker)
    if is_empty(data) or not isinstance(data, dict):
        raise ValueError(f"无 {broker} 的历史持仓数据。")
    rows = data.get("list", []) or []
    rows = [{
        "date": r.get("date"),
        "holding": _fmt_shares(r.get("holding")),
        "chg": _fmt_signed(r.get("chg")),
        "ratio%": r.get("ratio"),
    } for r in rows]

    result = {"symbol": symbol, "mode": "daily", "broker": broker, "points": len(rows), "series": rows}

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 经纪商 {broker} 历史持仓({len(rows)} 个交易日)")
    print()
    print_display_table(rows, columns=["date", "holding", "chg", "ratio%"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="港股经纪商持仓变动(仅HK)")
    parser.add_argument("symbol", help="港股代码,如 700.HK")
    parser.add_argument("--period", default="rct_1",
                        choices=["rct_1", "rct_5", "rct_20", "rct_60"],
                        help="统计周期(top模式): rct_1/5/20/60 日(默认近1日)")
    parser.add_argument("--detail", action="store_true", help="全量经纪商明细")
    parser.add_argument("--daily", action="store_true", help="单经纪商历史持仓(需配合 --broker)")
    parser.add_argument("--broker", default=None, help="经纪商ID(daily 模式必填,如 B01274)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_broker_holding(args.symbol, period=args.period, detail=args.detail,
                             daily=args.daily, broker=args.broker, output_json=args.output_json)
    except Exception as e:
        print_error("获取经纪商持仓", str(e))
        sys.exit(1)
