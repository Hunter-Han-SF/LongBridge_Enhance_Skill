"""获取长桥热度排行榜(综合热度/热度上升/热门交易/热议/关注度)。

对应 Longbridge CLI: rank / rank --key
官方 skill 无此加工分析。

热度综合: 交易活跃度 + 媒体报道 + 社区讨论 + 价格波动。

两种用法:
  1. 列出所有 tab(不传 --key):
     python get_heat_rank.py
     python get_heat_rank.py --market HK
     → 返回 [{key, market, name}],如 {key:'hot_all-us', name:'总热度'}
  2. 拉具体榜单(传 --key):
     python get_heat_rank.py --key hot_all-us
     python get_heat_rank.py --key trade_heat-hk --count 30
     → 返回上榜个股(symbol/name/价格/涨跌/资金流入/多周期动量)

常见 key:
  hot_all-{market}      总热度
  hot_up-{market}       热度上升
  trade_heat-{market}   热门交易
  discuss_heat-{market} 热议
  watchlist_heat-{market} 关注度
  market ∈ US/HK/CN/SG

用法:
    python get_heat_rank.py                              # 列所有 tab
    python get_heat_rank.py --market HK                  # 港股 tab
    python get_heat_rank.py --key hot_all-us             # 美股总热度榜
    python get_heat_rank.py --key trade_heat-hk --count 30 --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_heat_rank,
    get_heat_rank_keys,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _fmt_chg(v) -> str:
    """涨跌幅(小数)转百分比。"""
    f = to_float(v)
    if f is None:
        return str(v)
    pct = f * 100
    return f"{pct:+.2f}%"


def _fmt_inflow(v) -> str:
    """资金流入可读化。"""
    f = to_float(v)
    if f is None:
        return str(v)
    a = abs(f)
    sign = "+" if f > 0 else ("-" if f < 0 else "")
    if a >= 1e8:
        return f"{sign}{a/1e8:.2f}亿"
    if a >= 1e4:
        return f"{sign}{a/1e4:.2f}万"
    return f"{sign}{a:.0f}"


def fetch_heat_rank(
    market: str = "US",
    key: str | None = None,
    count: int = 20,
    output_json: bool = False,
) -> dict:
    if not key:
        return _list_tabs(market, output_json)
    return _show_rank(key, count, output_json)


def _list_tabs(market: str, output_json: bool) -> dict:
    tabs = get_heat_rank_keys(market=market)
    result = {"mode": "list_tabs", "market": market, "tabs": tabs}

    if output_json:
        print_json(result)
        return result

    if is_empty(tabs):
        print(f"无 {market} 热度榜 tab。")
        return result

    print(f"{market} 热度榜 tab 列表(用 --key <KEY> 拉具体榜单)")
    print()
    print_display_table(tabs, columns=["key", "market", "name"])
    print("\n示例: python get_heat_rank.py --key hot_all-us")
    return result


def _show_rank(key: str, count: int, output_json: bool) -> dict:
    data = get_heat_rank(key=key, count=count)
    lists = data["lists"]

    # 加工:涨跌幅转百分比、资金流入可读化
    for item in lists:
        item["chg_pct"] = _fmt_chg(item.get("chg"))
        item["five_day_pct"] = _fmt_chg(item.get("five_day_chg"))
        item["inflow_fmt"] = _fmt_inflow(item.get("inflow"))

    result = {
        "mode": "rank",
        "key": key,
        "count": len(lists),
        "updated_at": data["updated_at"],
        "lists": lists,
    }

    if output_json:
        print_json(result)
        return result

    if is_empty(lists):
        print(f"榜单 {key} 无数据。用不带 --key 的方式查看可用 tab。")
        return result

    print(f"热度榜 {key}({len(lists)} 名,更新 {data['updated_at']})")
    print()
    rows = [{
        "排名": str(i + 1),
        "symbol": item.get("symbol", ""),
        "名称": (item.get("name") or "")[:12],
        "现价": item.get("last_done", ""),
        "涨跌": item["chg_pct"],
        "5日": item["five_day_pct"],
        "资金流入": item["inflow_fmt"],
        "量比": item.get("volume_rate", ""),
    } for i, item in enumerate(lists)]
    print_display_table(rows, columns=["排名", "symbol", "名称", "现价", "涨跌", "5日", "资金流入", "量比"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="长桥热度排行榜")
    parser.add_argument("--market", default="US", help="市场(列 tab 时用): US|HK|CN|SG(默认 US)")
    parser.add_argument("--key", default=None,
                        help="榜单 key(如 hot_all-us)。留空则列出所有可用 tab")
    parser.add_argument("--count", type=int, default=20, help="返回条数(默认 20)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_heat_rank(market=args.market, key=args.key,
                        count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取热度榜", str(e))
        sys.exit(1)
