"""获取宏观经济数据发布日历(利率/CPI/PCE/非农/GDP 等)。

对应 Longbridge CLI: finance-calendar macrodata --market --star --start --end

每个事件含 star(1-3星)、Tier-1 重磅分级(FOMC/CPI/PCE/非农/失业率/GDP)与
data_kv(前值/预测值,公布后含实际值)。按指标查询历史用
scripts/sentiment/get_macro_data.py(维度互补:本脚本按日期,那个按指标)。

用法:
    python get_macro_calendar.py                          # 近期宏观事件
    python get_macro_calendar.py --market US --star 3     # 仅美国 3 星重磅
    python get_macro_calendar.py --market US --tier1      # 仅核心市场催化(FOMC/CPI/PCE/非农/GDP)
    python get_macro_calendar.py --json
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_finance_calendar,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
    to_int,
)

# 3 星核心宏观白名单(兼容中文与 CLI 默认英文名称): 识别可直接冲击全市场定价的一线宏观催化
TIER1_KEYWORDS = (
    "联邦基金利率",
    "利率决议",
    "fomc",
    "货币政策会议纪要",
    "federalfundsrate",
    "fedfundsrate",
    "interestratedecision",
    "cpi",
    "消费者物价指数",
    "consumerpriceindex",
    "pce",
    "个人消费支出(pce)物价",
    "核心pce",
    "personalconsumptionexpenditure",
    "pceprices",
    "非农就业",
    "nonfarmpayroll",
    "失业率",
    "unemploymentrate",
    "unemployment,rate",
    "初请失业金",
    "joblessclaims",
    "gdp",
    "国内生产总值",
    "grossdomesticproduct",
)


def classify_macro_tier(name: Any, star: int | None) -> str:
    """将宏观事件分级: tier1(核心市场催化) / tier2(其余 3 星) / regular(1-2 星)。"""
    norm = re.sub(r"\s+", "", str(name or "")).lower()
    if (star or 0) >= 3:
        if any(k in norm for k in TIER1_KEYWORDS):
            return "tier1"
        return "tier2"
    return "regular"


def _flatten_macro(buckets: list[dict]) -> list[dict]:
    events = []
    for b in buckets:
        b_date = str(b.get("date") or "").strip().replace(".", "-")
        for info in b.get("infos", []):
            if not isinstance(info, dict):
                continue
            kv = {kv.get("type", ""): kv.get("value", "")
                  for kv in (info.get("data_kv") or []) if isinstance(kv, dict)}
            kv_raw = {kv.get("type", ""): kv.get("value_raw", "")
                      for kv in (info.get("data_kv") or []) if isinstance(kv, dict)}

            raw_date = str(info.get("date") or "").strip()
            if re.match(r"^\d{4}[-.]\d{2}[-.]\d{2}", raw_date):
                event_date = raw_date[:10].replace(".", "-")
                clock = raw_date[10:].strip()
            else:
                event_date = b_date[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", b_date) else b_date
                clock = raw_date

            ts = to_float(info.get("datetime"))
            release_ts = int(ts) if (ts is not None and ts > 1e8) else None
            if release_ts is not None and not re.match(r"^\d{4}-\d{2}-\d{2}", event_date):
                event_date = datetime.fromtimestamp(release_ts, timezone.utc).strftime("%Y-%m-%d")

            display_dt = f"{event_date} {clock}".strip() if event_date else clock

            star_val = to_int(info.get("star"))
            if star_val is None:
                star_val = to_int((info.get("ext") or {}).get("importance"))

            name = str(info.get("content") or "")
            tier = classify_macro_tier(name, star_val)
            actual_val = str(kv.get("actual", "") or "")
            raw_actual = str(kv_raw.get("actual", "") or "").strip()
            released = bool(raw_actual) or (actual_val.strip() not in ("", "--", "None"))

            events.append({
                "name": name,
                "date": display_dt,
                "event_date": event_date,
                "time": clock,
                "datetime": info.get("datetime", ""),
                "release_ts": release_ts,
                "previous": str(kv.get("previous") or ""),
                "estimate": str(kv.get("estimate") or ""),
                "actual": actual_val,
                "released": released,
                "star": star_val,
                "stars": ("★" * star_val) if (star_val and 1 <= star_val <= 5) else "",
                "importance": star_val if star_val is not None else ((info.get("ext") or {}).get("importance") or ""),
                "tier": tier,
                "market": str(info.get("market") or ""),
            })
    return events


def fetch_macro_calendar(
    market: str | None = None,
    start: str | None = None,
    end: str | None = None,
    count: int = 50,
    star: int | None = None,
    tier1_only: bool = False,
    output_json: bool = False,
) -> dict:
    eff_star = 3 if (tier1_only and star is None) else star
    buckets = get_finance_calendar(
        category="macrodata",
        market=market,
        start=start,
        end=end,
        count=count,
        star=eff_star,
    )
    if is_empty(buckets):
        raise ValueError(f"近期无宏观事件({market or '全市场'})。")

    events = _flatten_macro(buckets)
    if eff_star is not None:
        events = [e for e in events if e.get("star") == eff_star]
    if tier1_only:
        events = [e for e in events if e.get("tier") == "tier1"]

    result = {
        "market": market or "ALL",
        "date_range": f"{buckets[0].get('date', '')} ~ {buckets[-1].get('date', '')}",
        "total_events": len(events),
        "tier1_count": sum(1 for e in events if e.get("tier") == "tier1"),
        "star_filter": eff_star,
        "tier1_only": tier1_only,
        "events": events,
    }

    if output_json:
        print_json(result)
        return result

    tag = " [仅 Tier-1 核心催化]" if tier1_only else (f" [{eff_star}星]" if eff_star else "")
    print(f"{market or '全市场'} 宏观经济数据日历{tag}({len(events)} 个事件,Tier-1 {result['tier1_count']} 项)")
    print(f"  日期范围: {result['date_range']}")
    print()
    rows = [{
        "星级": ("🔥★★★" if e.get("tier") == "tier1" else (e.get("stars") or "-")),
        "指标": (e.get("name") or "")[:30],
        "时间": e["date"],
        "前值": str(e["previous"])[:10],
        "预测": str(e["estimate"])[:10],
        "实际": str(e["actual"])[:10],
    } for e in events]
    print_display_table(rows, columns=["星级", "指标", "时间", "前值", "预测", "实际"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="宏观经济数据发布日历")
    parser.add_argument("--market", default=None, help="HK|US|CN|SG|EU|JP|...(留空=全市场)")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--count", type=int, default=50, help="返回事件数上限(默认 50)")
    parser.add_argument("--star", type=int, choices=[1, 2, 3], default=None,
                        help="重要性过滤(1/2/3 星)")
    parser.add_argument("--tier1", action="store_true",
                        help="仅显示 Tier-1 核心催化(FOMC/CPI/PCE/非农/失业率/GDP)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_macro_calendar(
            market=args.market,
            start=args.start,
            end=args.end,
            count=args.count,
            star=args.star,
            tier1_only=args.tier1,
            output_json=args.output_json,
        )
    except Exception as e:
        print_error("获取宏观日历", str(e))
        sys.exit(1)
