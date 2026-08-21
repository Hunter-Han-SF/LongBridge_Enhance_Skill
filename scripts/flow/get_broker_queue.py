"""获取港股买卖盘各价位的经纪商队列(带名称解析)。

对应 Longbridge CLI: brokers <SYMBOL> + participants(名称映射)
⚠️ 仅港股。与 broker-holding 联动:看出"哪家机构在哪一档挂单托盘"。

CLI 的 brokers 只返回每档的 broker_ids(无价格、无名称),本脚本:
  1. 用 participants 把 broker_id 解析成经纪商名称(摩根/高盛/瑞银/港股通...)
  2. 统计每个经纪商在买卖盘出现的档数(多档出现=大户托单)
  3. 队列快照与持仓变动结合,判断机构是否在护盘/出货

常见经纪商: 摩根士丹利/高盛/瑞银=外资投行;港股通(深/沪)=南向内资;
汇丰/花旗=托管行(长线机构);中银国际/海通国际=中资券商。

用法:
    python get_broker_queue.py 700.HK                 # 买卖各档队列+统计
    python get_broker_queue.py 700.HK --levels 5      # 只看前5档
    python get_broker_queue.py 700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_broker_queue,
    get_participants,
    is_empty,
    print_display_table,
    print_error,
    print_json,
)


def fetch_broker_queue(symbol: str, levels: int = 10, output_json: bool = False) -> dict:
    queue = get_broker_queue(symbol)
    if is_empty(queue["asks"]) and is_empty(queue["bids"]):
        raise ValueError(f"无经纪商队列数据。确认 {symbol} 是港股(仅 HK 支持 brokers 队列)。")

    participants = get_participants()
    name_map = {str(p["broker_id"]): (p.get("name_cn") or p.get("name_en") or p["broker_id"])
                for p in participants}

    def _resolve(ids: list) -> list[str]:
        out = []
        for bid in ids:
            out.append(name_map.get(str(bid), f"#{bid}"))
        return out

    counter: Counter = Counter()
    rows = []
    for side in ("bids", "asks"):
        for level in queue[side][:levels]:
            names = _resolve(level.get("broker_ids", []))
            side_label = "买" if side == "bids" else "卖"
            rows.append({
                "方向": side_label,
                "档位": level.get("position", ""),
                "经纪商家数": len(names),
                "队列": ", ".join(dict.fromkeys(names))[:60],  # 去重保序,截断
            })
            weight = 2 if (side == "bids" and level.get("position") == 1) else 1
            for n in dict.fromkeys(names):
                counter[(side, n)] += weight

    bid_top = [(n, c) for (side, n), c in counter.most_common() if side == "bids"][:10]
    ask_top = [(n, c) for (side, n), c in counter.most_common() if side == "asks"][:10]

    result = {
        "symbol": symbol,
        "levels_shown": levels,
        "queue": rows,
        "bid_brokers_top": [{"name": n, "level_presence": c} for n, c in bid_top],
        "ask_brokers_top": [{"name": n, "level_presence": c} for n, c in ask_top],
        "note": "level_presence 为该经纪商在前几档买/卖队列中出现的加权次数(买一档权重2)。"
                "配合 get_broker_holding.py 的持仓变动可判断机构托盘意图。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 经纪商买卖队列(前 {levels} 档)")
    print()
    print_display_table(rows, columns=["方向", "档位", "经纪商家数", "队列"])
    print()
    print("🟢 买盘出现最多的经纪商(潜在托单):")
    print_display_table([{"经纪商": n, "出现档数": c} for n, c in bid_top], columns=["经纪商", "出现档数"])
    print()
    print("🔴 卖盘出现最多的经纪商(潜在压单):")
    print_display_table([{"经纪商": n, "出现档数": c} for n, c in ask_top], columns=["经纪商", "出现档数"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="港股经纪商买卖队列(仅HK)")
    parser.add_argument("symbol", help="港股代码,如 700.HK")
    parser.add_argument("--levels", type=int, default=10, help="显示档位数(默认 10)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_broker_queue(args.symbol, levels=args.levels, output_json=args.output_json)
    except Exception as e:
        print_error("获取经纪商队列", str(e))
        sys.exit(1)
