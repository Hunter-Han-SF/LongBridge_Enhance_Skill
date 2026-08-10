"""获取涨跌异动榜(含关联新闻解读)。

对应 Longbridge CLI: top-movers --market --sort --count
与 anomaly(纯技术信号)不同,top-movers 把每个异动配上新闻解读。

当股票价格波动超过过去 ~20 交易日标准差时被标记,系统自动关联新闻解释原因。
排序: hot(热度,默认) | time(时间) | change(涨跌幅)

每条 event 含:
  - alert_reason: 异动原因(如"波动超 20 日均值")
  - counter_id / name: 标的
  - post: 关联新闻对象(desc_locale.original 是中文摘要,extract_summary 标记)

用法:
    python get_top_movers.py                         # 全市场热度排序
    python get_top_movers.py --market US             # 仅美股
    python get_top_movers.py --market HK --sort change  # 按涨跌幅排
    python get_top_movers.py --count 10
    python get_top_movers.py --json
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    counter_id_to_symbol,
    get_top_movers,
    is_empty,
    print_error,
    print_json,
)


def _strip_html(text: str) -> str:
    """去掉 HTML 标签和空白,纯文本摘要。"""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", clean).strip()


def _extract_summary(event: dict) -> str:
    """从 event.post 提取新闻摘要(优先中文 original,其次 html)。"""
    post = event.get("post") or {}
    if not isinstance(post, dict):
        return ""
    desc = post.get("desc_locale") or {}
    if isinstance(desc, dict):
        for key in ("original", "cn", "zh-CN"):
            t = desc.get(key)
            if t:
                return _strip_html(t)
    return _strip_html(post.get("description_html", ""))


def fetch_top_movers(
    market: str | None = None,
    sort: str = "hot",
    count: int = 20,
    output_json: bool = False,
) -> dict:
    data = get_top_movers(market=market, sort=sort, count=count)
    events = data["events"]

    # 加工:标的在 event.stock(symbol/name/last_done/change),新闻摘要从 post 提取
    for ev in events:
        stock = ev.get("stock") or {}
        ev["symbol"] = stock.get("symbol") or ev.get("symbol") or ""
        ev["name"] = stock.get("name") or stock.get("full_name") or ev.get("name") or ""
        ev["price"] = stock.get("last_done")
        ev["change"] = stock.get("change")
        ev["summary"] = _extract_summary(ev)
        ev["summary_short"] = (ev["summary"][:60] + "...") if len(ev["summary"]) > 60 else ev["summary"]

    result = {
        "market": market or "ALL",
        "sort": sort,
        "count": len(events),
        "updated_at": data["updated_at"],
        "events": events,
    }

    if output_json:
        print_json(result)
        return result

    if is_empty(events):
        print(f"{market or '全市场'}:无异动榜数据。")
        return result

    sort_label = {"hot": "热度", "time": "时间", "change": "涨跌幅"}.get(sort, sort)
    print(f"{market or '全市场'} 涨跌异动榜(按{sort_label}排序,{len(events)} 条)")
    print(f"更新时间: {data['updated_at']}")
    print()
    for i, ev in enumerate(events, 1):
        price_str = f"${ev.get('price','?')}" if ev.get("price") else ""
        chg_str = f"({ev.get('change','')})" if ev.get("change") else ""
        print(f"[{i}] {ev.get('symbol','?')} {ev.get('name','')} {price_str} {chg_str}  — {ev.get('alert_reason','')}")
        if ev["summary_short"]:
            print(f"    📰 {ev['summary_short']}")
        print()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="涨跌异动榜(含关联新闻)")
    parser.add_argument("--market", default=None, help="HK|US|CN|SG(留空=全市场)")
    parser.add_argument("--sort", default="hot", choices=["hot", "time", "change"],
                        help="排序: hot(热度)/time(时间)/change(涨跌幅)")
    parser.add_argument("--count", type=int, default=20, help="返回条数(默认 20)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_top_movers(market=args.market, sort=args.sort,
                         count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取异动榜", str(e))
        sys.exit(1)
