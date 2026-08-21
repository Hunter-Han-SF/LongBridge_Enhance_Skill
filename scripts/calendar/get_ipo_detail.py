"""获取单只 IPO 的详情档案(招股书摘要/基石投资者/时间线/申购额度)。

对应 Longbridge CLI: ipo detail <SYMBOL>

用法:
    python get_ipo_detail.py 3223.HK
    python get_ipo_detail.py 3223.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_ipo_detail,
    is_empty,
    print_display_table,
    print_error,
    print_json,
)


def fetch_ipo_detail(symbol: str, output_json: bool = False) -> dict:
    data = get_ipo_detail(symbol)
    if is_empty(data):
        raise ValueError(f"无 IPO 详情({symbol})。确认是近期 IPO 标的(用 get_ipo_listings.py 查)。")

    profile = data.get("profile") or {}
    market_profile = profile.get("hk") or profile.get("us") or {}
    holdings = data.get("holdings") or {}
    result = {
        "symbol": symbol,
        "profile": market_profile,
        "cornerstone_investors": market_profile.get("investors", []),
        "timeline": data.get("timeline", []),
        "holdings": holdings,
        "eligibility": data.get("eligibility", {}),
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} IPO 详情")
    print()
    info = market_profile if isinstance(market_profile, dict) else {}
    kv = {k: v for k, v in info.items()
          if k not in ("investors", "counter_id") and v not in ("", None, [], {})}
    rows = [{"项目": k, "值": str(v)[:60]} for k, v in kv.items()]
    if rows:
        print("📋 招股档案:")
        print_display_table(rows, columns=["项目", "值"])
        print()

    investors = market_profile.get("investors") or []
    if investors:
        print(f"🏛 基石投资者({len(investors)} 家):")
        inv_rows = [{
            "名称": str(i.get("name", ""))[:30],
            "认购金额": i.get("subscribe_value", ""),
            "占比%": i.get("capital_ratio", ""),
        } for i in investors]
        print_display_table(inv_rows, columns=["名称", "认购金额", "占比%"])
        print()

    holdings_rows = {k: v for k, v in holdings.items() if v not in ("", None)}
    if holdings_rows:
        print("💰 申购额度:")
        print_display_table([{"项目": k, "值": v} for k, v in holdings_rows.items()],
                            columns=["项目", "值"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IPO 详情档案")
    parser.add_argument("symbol", help="IPO 代码,如 3223.HK")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_ipo_detail(args.symbol, output_json=args.output_json)
    except Exception as e:
        print_error("获取 IPO 详情", str(e))
        sys.exit(1)
