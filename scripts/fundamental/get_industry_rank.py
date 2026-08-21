"""行业板块排行 + 行业层级树 + 行业估值分布(板块轮动监控)。

对应 Longbridge CLI: industry-rank --market / industry-peers <BK_COUNTER_ID> /
industry-valuation dist <SYMBOL>
三种模式:
  1. rank(默认): 各分类下行业涨跌幅排行(含领涨股)
  2. peers: 某行业在层级树中的位置与子行业 --peers BK/US/IN00362
  3. valuation: 标的当前估值 vs 行业内排名(分位) --valuation AAPL.US

用法:
    python get_industry_rank.py --market US                # 行业排行
    python get_industry_rank.py --market US --count 10
    python get_industry_rank.py --peers BK/US/IN00362      # 行业层级树
    python get_industry_rank.py --valuation AAPL.US        # 行业估值分布
    python get_industry_rank.py --market HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_industry_peers,
    get_industry_rank,
    get_industry_valuation_dist,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _rank_mode(market: str, count: int, output_json: bool) -> dict:
    items = get_industry_rank(market=market)
    if is_empty(items):
        raise ValueError(f"无行业排行数据({market})。")
    result = {"mode": "rank", "market": market, "categories": items}
    if output_json:
        print_json(result)
        return result

    for cat in items:
        lists = cat.get("lists", [])
        if not lists:
            continue
        print(f"{cat.get('name', '')}(共 {len(lists)} 个行业,按涨跌排序)")
        rows = [{
            "行业": str(l.get("name", ""))[:16],
            "BK id": l.get("counter_id", ""),
            # JSON 的 chg 是分数形式(0.1544 = +15.44%,与 CLI pretty 输出对照确认)
            "涨跌%": round(to_float(l.get("chg")) * 100, 2)
                if to_float(l.get("chg")) is not None else "",
            "领涨股": f"{l.get('leading_ticker', '')} {str(l.get('leading_name', ''))[:10]}",
            "领涨%": round(to_float(l.get("leading_chg")) * 100, 2)
                if to_float(l.get("leading_chg")) is not None else "",
        } for l in lists[:count]]
        print_display_table(rows, columns=["行业", "BK id", "涨跌%", "领涨股", "领涨%"])
        print()
    print("提示: 用 --peers <BK id> 查行业层级树")
    return result


def _peers_mode(counter_id: str, output_json: bool) -> dict:
    data = get_industry_peers(counter_id)
    chain, top = data.get("chain"), data.get("top")
    if not chain:
        raise ValueError(f"无行业层级数据({counter_id})。确认 BK id 来自 rank 模式的输出。")
    result = {"mode": "peers", "counter_id": counter_id, "chain": chain, "top": top}
    if output_json:
        print_json(result)
        return result
    print(f"{counter_id} 行业层级树")
    print(f"  一级行业: {top.get('name') if top else ''}")
    print(f"  本行业: {chain.get('name', '')}(成分股 {chain.get('stock_num', '?')} 只,"
          f"level {chain.get('level')})")
    children = chain.get("next") or []
    if children:
        print("  子行业:")
        rows = [{"子行业": str(c.get("name", ""))[:20],
                 "BK id": c.get("counter_id", ""),
                 "成分股数": c.get("stock_num", "")} for c in children]
        print_display_table(rows, columns=["子行业", "BK id", "成分股数"])
    return result


def _valuation_mode(symbol: str, output_json: bool) -> dict:
    """行业估值分布:当前值 vs 行业内排名(industry-valuation dist)。"""
    dist = get_industry_valuation_dist(symbol)
    if is_empty(dist):
        raise ValueError(f"无行业估值分布数据({symbol})。小票/新股常无覆盖。")
    result = {"mode": "valuation", "symbol": symbol, "distribution": dist}
    if output_json:
        print_json(result)
        return result
    print(f"{symbol} 行业估值分布")
    print()
    rows = []
    for metric in ("pe", "pb", "ps"):
        d = dist.get(metric)
        if not d:
            continue
        ranking = to_float(d.get("ranking"))
        verdict = ""
        if ranking is not None:
            verdict = ("行业内偏贵" if ranking > 0.7 else
                       "行业内便宜" if ranking < 0.3 else "行业中位")
        rows.append({
            "指标": metric.upper(),
            "当前值": round(to_float(d.get("value")), 2)
                if to_float(d.get("value")) is not None else "",
            "行业中位": round(to_float(d.get("median")), 2)
                if to_float(d.get("median")) is not None else "",
            "行业区间": f"{to_float(d.get('low')):.2f} ~ {to_float(d.get('high')):.2f}"
                if to_float(d.get("low")) is not None else "",
            "排名": f"{d.get('rank_index')}/{d.get('rank_total')}",
            "分位": round(ranking * 100, 1) if ranking is not None else "",
            "判断": verdict,
        })
    print_display_table(rows, columns=["指标", "当前值", "行业中位", "行业区间", "排名", "分位", "判断"])
    return result


def fetch_industry_rank(
    market: str = "US",
    peers: str | None = None,
    valuation: str | None = None,
    count: int = 10,
    output_json: bool = False,
) -> dict:
    if valuation:
        return _valuation_mode(valuation, output_json)
    if peers:
        return _peers_mode(peers, output_json)
    return _rank_mode(market, count, output_json)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="行业排行+层级树+行业估值分布")
    parser.add_argument("--market", default="US", choices=["US", "HK", "CN", "SG"],
                        help="市场(默认 US)")
    parser.add_argument("--peers", default=None, help="行业层级树模式,传 BK counter_id")
    parser.add_argument("--valuation", default=None,
                        help="行业估值分布模式,传标的代码如 AAPL.US")
    parser.add_argument("--count", type=int, default=10, help="每分类显示行业数(默认 10)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_industry_rank(market=args.market, peers=args.peers,
                            valuation=args.valuation, count=args.count,
                            output_json=args.output_json)
    except Exception as e:
        print_error("获取行业排行", str(e))
        sys.exit(1)
