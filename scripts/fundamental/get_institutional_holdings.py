"""13F 机构持仓:机构 AUM 排名 / 单机构持仓 / 两期持仓变动。

对应 Longbridge CLI: investors [CIK] / investors changes <CIK>
三种模式:
  1. rankings(默认): 13F 机构 AUM 排名(拿 CIK)
  2. holdings: 某机构最新持仓 --cik 0001422848
  3. changes: 最近两期 13F 的持仓变动(新建/加仓/减仓/清仓) --cik ... --changes

⚠️ 数据为美股 13F 披露(仅 US 股票,季度延迟 45 天)。

用法:
    python get_institutional_holdings.py                          # AUM 排名
    python get_institutional_holdings.py --cik 0001422848         # 持仓
    python get_institutional_holdings.py --cik 0001422848 --changes
    python get_institutional_holdings.py --json
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_investor_changes,
    get_investor_holdings,
    get_investor_rankings,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _fmt_usd(v) -> str:
    f = to_float(v)
    if f is None:
        return ""
    if abs(f) >= 1e12:
        return f"{f/1e12:.2f}万亿$"
    if abs(f) >= 1e9:
        return f"{f/1e9:.1f}B$"
    if abs(f) >= 1e6:
        return f"{f/1e6:.1f}M$"
    return f"{f:,.0f}$"


def _rankings_mode(output_json: bool) -> dict:
    rankings = get_investor_rankings()
    if is_empty(rankings):
        raise ValueError("无机构排名数据。")
    result = {"mode": "rankings", "count": len(rankings), "rankings": rankings}
    if output_json:
        print_json(result)
        return result
    print(f"13F 机构 AUM 排名(共 {len(rankings)} 家,--cik <CIK> 查持仓)")
    print()
    rows = [{
        "rank": r.get("rank", ""),
        "机构": str(r.get("name", ""))[:36],
        "CIK": r.get("cik", ""),
        "AUM": _fmt_usd(r.get("aum_usd")),
        "报告期": r.get("period", ""),
    } for r in rankings]
    print_display_table(rows, columns=["rank", "机构", "CIK", "AUM", "报告期"])
    return result


def _holdings_mode(cik: str, count: int, output_json: bool) -> dict:
    data = get_investor_holdings(cik)
    holdings = data.get("holdings", [])
    if is_empty(holdings):
        raise ValueError(f"无持仓数据(CIK={cik})。CIK 来自 rankings 模式输出。")
    holdings.sort(key=lambda h: to_float(h.get("value_usd")) or 0, reverse=True)
    result = {"mode": "holdings", "cik": data.get("cik", cik),
              "firm": data.get("firm"), "filing_date": data.get("filing_date"),
              "total_positions": len(holdings), "holdings": holdings[:count]}
    if output_json:
        print_json(result)
        return result
    print(f"{data.get('firm')} 13F 持仓(申报 {data.get('filing_date')},"
          f"共 {len(holdings)} 个位置,显示前 {count})")
    print()
    rows = [{
        "股票": str(h.get("name", ""))[:28],
        "cusip": h.get("cusip", ""),
        "股数": f"{to_float(h.get('shares')) or 0:,.0f}",
        "市值": _fmt_usd(h.get("value_usd")),
        "权重%": h.get("weight_pct", ""),
    } for h in holdings[:count]]
    print_display_table(rows, columns=["股票", "cusip", "股数", "市值", "权重%"])
    return result


def _changes_mode(cik: str, count: int, output_json: bool) -> dict:
    data = get_investor_changes(cik)
    changes = data.get("changes", [])
    if is_empty(changes):
        raise ValueError(f"无持仓变动数据(CIK={cik})。")
    action_counter = Counter(str(c.get("action", "")) for c in changes)
    action_label = {"NEW": "新建", "ADDED": "加仓", "REDUCED": "减仓", "EXITED": "清仓"}
    biggest_new = max((c for c in changes if c.get("action") == "NEW"),
                      key=lambda c: to_float(c.get("delta_usd")) or 0, default=None)
    result = {
        "mode": "changes", "cik": cik,
        "summary": {action_label.get(a, a): n for a, n in action_counter.items()},
        "biggest_new_position": biggest_new,
        "changes": changes[:count],
    }
    if output_json:
        print_json(result)
        return result
    print(f"13F 持仓变动(CIK={cik},共 {len(changes)} 条)")
    print("  " + " / ".join(f"{action_label.get(a, a)} {n}" for a, n in action_counter.items()))
    if biggest_new:
        print(f"  最大新建: {biggest_new.get('name')}"
              f"({_fmt_usd(biggest_new.get('delta_usd'))})")
    print()
    rows = [{
        "动作": action_label.get(str(c.get("action", "")), c.get("action", "")),
        "股票": str(c.get("name", ""))[:26],
        "本期股数": f"{to_float(c.get('shares')) or 0:,.0f}",
        "上期股数": f"{to_float(c.get('prev_shares')) or 0:,.0f}",
        "市值": _fmt_usd(c.get("value_usd")),
        "变动额": _fmt_usd(c.get("delta_usd")),
    } for c in changes[:count]]
    print_display_table(rows, columns=["动作", "股票", "本期股数", "上期股数", "市值", "变动额"])
    return result


def fetch_institutional_holdings(
    cik: str | None = None,
    changes: bool = False,
    count: int = 20,
    output_json: bool = False,
) -> dict:
    if cik:
        if changes:
            return _changes_mode(cik, count, output_json)
        return _holdings_mode(cik, count, output_json)
    if changes:
        raise ValueError("--changes 需要配合 --cik <CIK>")
    return _rankings_mode(output_json)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="13F 机构持仓(排名/持仓/变动)")
    parser.add_argument("--cik", default=None, help="机构 CIK(来自 rankings 输出),如 0001422848")
    parser.add_argument("--changes", action="store_true", help="查最近两期持仓变动(需 --cik)")
    parser.add_argument("--count", type=int, default=20, help="显示条数(默认 20)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_institutional_holdings(cik=args.cik, changes=args.changes,
                                     count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取机构持仓", str(e))
        sys.exit(1)
