"""获取港股涡轮/权证数据(列表 / 单合约报价 / 发行商)。

对应 Longbridge CLI: warrant <SYMBOL> / warrant quote <SYM...> / warrant issuers
⚠️ 仅港股。这是模块①(衍生品)的港股补位:此前期权模块只覆盖美股 OPRA。

三种模式:
  1. list 模式(默认): 正股的全部涡轮,附统计(数量/到期分布/杠杆分布)
     --sort leverage|expiry|price  --bull/--bear 过滤(经 quote 抽样判断方向)
  2. quote 模式: 指定合约的实时报价(Bull/Bear 方向 + implied_vol)
  3. issuers 模式: 发行商列表(发行人集中度)

已知坑(实测 2026-08-21):
  - warrant list 的 type 字段全是 'Call',不可信;真实方向以 quote 的
    type('Bull'认购/'Bear'认沽)为准。list 模式的 --enrich 用 quote 批量补全方向。
  - quote 的 implied_vol 实测常见 0.000(无数据),仅作参考。

用法:
    python get_warrant.py 700.HK                          # 全部涡轮+统计
    python get_warrant.py 700.HK --sort leverage --count 15
    python get_warrant.py 700.HK --enrich 20              # 前20条补全真实方向
    python get_warrant.py 700.HK --quote 61304.HK 53472.HK
    python get_warrant.py --issuers
    python get_warrant.py 700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_warrant_issuers,
    get_warrant_list,
    get_warrant_quote,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


BULL_TYPES = ("Bull", "Call", "认购")  # 实测 quote 的 type 混用 Call/Bull 表示认购


def _direction_label(v) -> str:
    s = str(v or "")
    if s in BULL_TYPES:
        return "认购"
    if s in ("Bear", "Put", "认沽"):
        return "认沽"
    return s


def _list_mode(symbol: str, sort: str, count: int, enrich: int,
               direction: str | None, output_json: bool) -> dict:
    warrants = get_warrant_list(symbol)
    if is_empty(warrants):
        raise ValueError(f"无涡轮数据。确认 {symbol} 是港股且发行过涡轮(非港股不支持)。")

    # enrich: 用 quote 批量补全真实方向(list 的 type 不可信,实测存在 list=Call/quote=Bear)
    enriched: dict[str, dict] = {}
    if enrich > 0:
        sample = sorted(warrants, key=lambda w: to_float(w.get("leverage_ratio")) or 0,
                        reverse=True)[:enrich]
        for i in range(0, len(sample), 10):
            batch = [w["symbol"] for w in sample[i:i + 10]]
            for q in get_warrant_quote(batch):
                enriched[str(q.get("symbol"))] = q

    rows = []
    for w in warrants:
        q = enriched.get(str(w.get("symbol")), {})
        rows.append({
            "symbol": w.get("symbol", ""),
            "名称": w.get("name", ""),
            "方向": _direction_label(q.get("type") or w.get("type")),
            "到期日": w.get("expiry", ""),
            "现价": to_float(w.get("last")),
            "杠杆": round(to_float(w.get("leverage_ratio")) or 0, 2),
            "IV": to_float(q.get("implied_vol")),
        })
    if direction:  # --bull/--bear 只在 enrich 覆盖范围内过滤
        want = "认购" if direction == "bull" else "认沽"
        rows = [r for r in rows if r["方向"] == want]

    key_map = {"leverage": "杠杆", "expiry": "到期日", "price": "现价"}
    rows.sort(key=lambda r: (to_float(r[key_map[sort]]) or 0), reverse=(sort != "expiry"))
    total = len(rows)
    shown = rows[:count]

    # 统计:到期年份分布 + 杠杆分布
    years: dict[str, int] = {}
    for w in warrants:
        y = str(w.get("expiry", ""))[:4]
        if y:
            years[y] = years.get(y, 0) + 1
    levs = [to_float(w.get("leverage_ratio")) or 0 for w in warrants]

    result = {
        "symbol": symbol,
        "mode": "list",
        "total": total,
        "enriched": len(enriched),
        "expiry_distribution": dict(sorted(years.items())),
        "leverage": {
            "max": round(max(levs), 2) if levs else None,
            "median": round(sorted(levs)[len(levs) // 2], 2) if levs else None,
            "min": round(min(levs), 2) if levs else None,
        },
        "note": "list 的 type 字段不可信(实测存在 list=Call/quote=Bear);"
                "方向列在 --enrich 覆盖范围内取自 quote",
        "warrants": rows,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 港股涡轮(共 {total} 只,杠杆中位数 {result['leverage']['median']})")
    print(f"  到期分布: " + " / ".join(f"{y}年{c}只" for y, c in result["expiry_distribution"].items()))
    print(f"  杠杆范围: {result['leverage']['min']} ~ {result['leverage']['max']}")
    print()
    print_display_table(shown, columns=["symbol", "名称", "方向", "到期日", "现价", "杠杆", "IV"])
    if total > count:
        print(f"... 共 {total} 只,仅显示前 {count} 只(--count 调整)")
    return result


def _quote_mode(symbol: str, quotes: list[str], output_json: bool) -> dict:
    rows = get_warrant_quote(quotes)
    if is_empty(rows):
        raise ValueError(f"无涡轮报价数据: {', '.join(quotes)}。确认是港股涡轮代码。")
    result = {
        "symbol": symbol,
        "mode": "quote",
        "quotes": rows,
    }
    if output_json:
        print_json(result)
        return result
    print(f"涡轮实时报价({len(rows)} 只)")
    print()
    table = [{
        "symbol": q.get("symbol", ""),
        "方向": _direction_label(q.get("type")),
        "到期日": q.get("expiry", ""),
        "现价": q.get("last", ""),
        "昨收": q.get("prev_close", ""),
        "IV": q.get("implied_vol", ""),
    } for q in rows]
    print_display_table(table, columns=["symbol", "方向", "到期日", "现价", "昨收", "IV"])
    return result


def _issuers_mode(output_json: bool) -> dict:
    issuers = get_warrant_issuers()
    if is_empty(issuers):
        raise ValueError("无发行商数据。")
    result = {"mode": "issuers", "count": len(issuers), "issuers": issuers}
    if output_json:
        print_json(result)
        return result
    print(f"涡轮发行商(共 {len(issuers)} 家)")
    print()
    print_display_table(issuers, columns=["id", "name_cn", "name_en"])
    return result


def fetch_warrant(
    symbol: str,
    quote: list[str] | None = None,
    issuers: bool = False,
    sort: str = "leverage",
    count: int = 20,
    enrich: int = 0,
    direction: str | None = None,
    output_json: bool = False,
) -> dict:
    if issuers:
        return _issuers_mode(output_json)
    if quote:
        return _quote_mode(symbol, quote, output_json)
    if not symbol:
        raise ValueError("list 模式必须提供正股代码,如 700.HK(或用 --issuers / --quote)")
    return _list_mode(symbol, sort, count, enrich, direction, output_json)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="港股涡轮/权证数据(仅HK)")
    parser.add_argument("symbol", nargs="?", default=None, help="正股代码,如 700.HK")
    parser.add_argument("--quote", nargs="+", default=None, help="涡轮合约报价模式,如 61304.HK 53472.HK")
    parser.add_argument("--issuers", action="store_true", help="发行商列表模式")
    parser.add_argument("--sort", default="leverage", choices=["leverage", "expiry", "price"],
                        help="排序字段(默认 leverage 降序)")
    parser.add_argument("--count", type=int, default=20, help="显示条数(默认 20)")
    parser.add_argument("--enrich", type=int, default=0,
                        help="用 quote 补全前 N 只的方向/IV(每次批量10只,默认 0)")
    parser.add_argument("--bull", dest="direction", action="store_const", const="bull",
                        help="仅认购(需配合 --enrich)")
    parser.add_argument("--bear", dest="direction", action="store_const", const="bear",
                        help="仅认沽(需配合 --enrich)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_warrant(
            symbol=args.symbol, quote=args.quote, issuers=args.issuers,
            sort=args.sort, count=args.count, enrich=args.enrich,
            direction=args.direction, output_json=args.output_json,
        )
    except Exception as e:
        print_error("获取涡轮数据", str(e))
        sys.exit(1)
