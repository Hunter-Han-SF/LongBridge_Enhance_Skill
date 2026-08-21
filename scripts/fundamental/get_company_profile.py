"""获取公司档案(概况 + 高管团队,一次聚合)。

对应 Longbridge CLI: company <SYMBOL> + executive <SYMBOL>
输出:成立年份/员工数/地址/管理层/审计/法律代表 + 高管列表(姓名/职务/背景)。

用法:
    python get_company_profile.py AAPL.US
    python get_company_profile.py AAPL.US --execs 8
    python get_company_profile.py 700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_company_profile,
    get_executives,
    is_empty,
    print_display_table,
    print_error,
    print_json,
)

# company 返回的字段大多是空的(按标的覆盖度不同),只显示有值的
_KEY_LABELS = {
    "company_name": "公司名称", "founded": "成立年份", "employees": "员工数",
    "address": "地址", "Phone": "电话", "manager": "总经理", "chairman": "董事长",
    "legal_repr": "法人代表", "listing_date": "上市日期", "issue_price": "发行价",
    "accounting_firm": "会计师事务所", "audit_inst": "审计机构",
    "legal_counsel": "法律顾问", "category": "分类", "bus_license": "工商执照",
}


def fetch_company_profile(symbol: str, execs_count: int = 10,
                          output_json: bool = False) -> dict:
    profile = get_company_profile(symbol)
    if is_empty(profile):
        raise ValueError(f"无公司档案数据({symbol})。")

    professionals = get_executives(symbol)
    exec_rows = []
    for pl in professionals:
        for p in pl.get("professionals", []):
            exec_rows.append({
                "name": p.get("name", ""),
                "title": p.get("title", ""),
                "biography": str(p.get("biography", ""))[:120],
            })

    shown = {label: profile.get(key) for key, label in _KEY_LABELS.items()
             if profile.get(key) not in ("", None)}
    result = {
        "symbol": symbol,
        "profile": shown,
        "profile_raw": profile,
        "executives": exec_rows,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 公司档案")
    print()
    if shown:
        print_display_table([{"项目": k, "值": str(v)[:56]} for k, v in shown.items()],
                            columns=["项目", "值"])
        print()
    if exec_rows:
        print(f"👥 高管团队(共 {len(exec_rows)} 人,显示前 {execs_count})")
        rows = [{
            "姓名": e["name"],
            "职务": str(e["title"])[:24],
            "背景": e["biography"][:40],
        } for e in exec_rows[:execs_count]]
        print_display_table(rows, columns=["姓名", "职务", "背景"])
    else:
        print("(无高管数据)")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="公司档案(概况+高管)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 700.HK")
    parser.add_argument("--execs", type=int, default=10, help="显示高管数(默认 10)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_company_profile(args.symbol, execs_count=args.execs,
                              output_json=args.output_json)
    except Exception as e:
        print_error("获取公司档案", str(e))
        sys.exit(1)
