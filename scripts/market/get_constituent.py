"""获取指数/ETF 成分股(板块轮动监控 + 指内强弱分析)。

对应 Longbridge CLI: constituent <INDEX> [--sort] [--order]
指数符号: 港股 HSI.HK;美股指数前缀点 .SPX.US/.DJI.US/.IXIC.US;ETF 如 IVV.US
(美股 ETF 默认拉 SEC EDGAR N-PORT 全持仓)。

sort 可选: change(涨跌) price turnover inflow(资金流入!) turnover-rate market-cap

用法:
    python get_constituent.py HSI.HK                          # 恒指成分,按涨跌
    python get_constituent.py .SPX.US --sort inflow           # 标普500按资金流入
    python get_constituent.py IVV.US --limit 20               # ETF 持仓
    python get_constituent.py HSI.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    counter_id_to_symbol,
    get_constituent,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _fmt_big(v) -> str:
    f = to_float(v)
    if f is None:
        return ""
    if abs(f) >= 1e12:
        return f"{f/1e12:.2f}万亿"
    if abs(f) >= 1e8:
        return f"{f/1e8:.1f}亿"
    return f"{f:,.0f}"


def fetch_constituent(index_symbol: str, limit: int = 20, sort: str = "change",
                      order: str = "desc", output_json: bool = False) -> dict:
    data = get_constituent(index_symbol, limit=limit, sort=sort, order=order)
    stocks = data.get("stocks", [])
    if is_empty(stocks):
        raise ValueError(f"无成分股数据({index_symbol})。美股指数需前缀点(.SPX.US),"
                         f"港股指数直接 HSI.HK。")

    for s in stocks:
        s["symbol"] = counter_id_to_symbol(s.get("counter_id", "")) or s.get("counter_id", "")
        chg = to_float(s.get("chg"))
        s["chg_pct"] = round(chg * 100, 2) if chg is not None and abs(chg) < 15 else chg

    rise, fall, flat = data.get("rise_num"), data.get("fall_num"), data.get("flat_num")
    total_inflow = sum(to_float(s.get("inflow")) or 0 for s in stocks)

    result = {
        "index": index_symbol,
        "sort": sort, "order": order,
        "breadth": {"rise": rise, "fall": fall, "flat": flat},
        "shown": len(stocks),
        "total_inflow": total_inflow,
        "stocks": stocks,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{index_symbol} 成分股(显示 {len(stocks)} 只,按 {sort} {order})")
    # 部分指数(如 HSI)不返回广度数据,全 0 时不显示
    if (rise or 0) + (fall or 0) + (flat or 0) > 0:
        print(f"  广度: 上涨 {rise} / 下跌 {fall} / 平 {flat}"
              f" → {'普涨' if (rise or 0) > (fall or 0) else '普跌' if (fall or 0) > (rise or 0) else '均衡'}")
    if total_inflow:
        print(f"  展示成分合计资金流入: {_fmt_big(total_inflow)}")
    print()
    rows = [{
        "symbol": s["symbol"],
        "名称": str(s.get("name", ""))[:10],
        "现价": s.get("last_done", ""),
        "涨跌%": s.get("chg_pct", ""),
        "成交额": _fmt_big(s.get("turnover")),
        "资金流入": _fmt_big(s.get("inflow")),
        "标签": ",".join(s.get("tags", []) or [])[:12],
    } for s in stocks]
    print_display_table(rows, columns=["symbol", "名称", "现价", "涨跌%", "成交额", "资金流入", "标签"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="指数/ETF 成分股(板块轮动)")
    parser.add_argument("index", help="指数/ETF 代码,如 HSI.HK / .SPX.US / IVV.US")
    parser.add_argument("--limit", type=int, default=20, help="返回数量(默认 20)")
    parser.add_argument("--sort", default="change",
                        choices=["change", "price", "turnover", "inflow",
                                 "turnover-rate", "market-cap"],
                        help="排序字段(默认 change)")
    parser.add_argument("--order", default="desc", choices=["desc", "asc"], help="排序方向")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_constituent(args.index, limit=args.limit, sort=args.sort,
                          order=args.order, output_json=args.output_json)
    except Exception as e:
        print_error("获取成分股", str(e))
        sys.exit(1)
