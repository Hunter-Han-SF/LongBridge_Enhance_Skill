"""按阶段列出 IPO 新股(认购中 / 待上市暗盘 / 已上市)。

对应 Longbridge CLI: ipo subscriptions / wait-listing / listed / us-*
比 get_ipo_calendar.py(按日期)更细:含发行价/暗盘时段/中签率/申购状态。

用法:
    python get_ipo_listings.py                                    # 待上市(暗盘)
    python get_ipo_listings.py --stage subscriptions              # 认购中
    python get_ipo_listings.py --stage listed                     # 已上市
    python get_ipo_listings.py --stage us-wait-listing            # 美股暗盘
    python get_ipo_listings.py --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone, tzinfo

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_ipo_listings,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)

_STAGES = [
    "subscriptions", "wait-listing", "listed",
    "us-subscriptions", "us-wait-listing", "us-listed",
]


class _EtRuleTz(tzinfo):
    """美东时区(zoneinfo/tzdata 不可用时的纯算法兜底):
    夏令时 3月第2个周日 2:00 起 -4,11月第1个周日 2:00 止回落 -5。"""

    def utcoffset(self, dt):
        if dt is None:
            return None
        naive = dt.replace(tzinfo=None)

        def _nth_wd(month, weekday, n):
            first = datetime(naive.year, month, 1).weekday()
            return 1 + (weekday - first) % 7 + 7 * (n - 1)

        dst = (datetime(naive.year, 3, _nth_wd(3, 6, 2), 2) <= naive
               < datetime(naive.year, 11, _nth_wd(11, 6, 1), 2))
        return timedelta(hours=-4 if dst else -5)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "US/Eastern"


def _market_tz(market: str):
    """IPO 市场代码 → 当地时区。上市日时间戳是当地午夜(实测 HK ipo_date
    =香港 0 点),按 UTC 解析会提前一天。HK 固定 UTC+8;US 美东(zoneinfo
    优先,无 tzdata 时退纯算法);其余市场维持 UTC 旧行为。"""
    m = str(market).lower()
    if m == "hk":
        return timezone(timedelta(hours=8))
    if m == "us":
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo("America/New_York")
        except Exception:
            return _EtRuleTz()
    return timezone.utc


def _days_until(ts, tz) -> str:
    f = to_float(ts)
    if not f:
        return ""
    d = datetime.fromtimestamp(f, tz=tz).date()
    delta = (d - datetime.now(tz).date()).days
    return f"{delta:+d}天" if delta != 0 else "今天"


def fetch_ipo_listings(stage: str = "wait-listing", output_json: bool = False) -> dict:
    data = get_ipo_listings(stage=stage)
    if is_empty(data):
        raise ValueError(f"该阶段无 IPO 数据({stage})。试试其他 --stage: {', '.join(_STAGES)}")

    result = {"stage": stage, "markets": {}}
    for market, items in data.items():
        if not items:
            continue
        tz = _market_tz(market)
        for it in items:
            it["days_to_ipo"] = _days_until(it.get("ipo_date"), tz)
        result["markets"][market] = items

    if not result["markets"]:
        raise ValueError(f"该阶段暂无在列 IPO({stage})。")

    if output_json:
        print_json(result)
        return result

    stage_label = {"subscriptions": "认购中", "wait-listing": "待上市(暗盘)",
                   "listed": "已上市"}.get(stage.replace("us-", ""), stage)
    for market, items in result["markets"].items():
        tz = _market_tz(market)
        print(f"{market.upper()} {stage_label} IPO({len(items)} 只)")
        print()
        rows = [{
            "symbol": it.get("symbol", ""),
            "名称": str(it.get("name", ""))[:12],
            "发行价": it.get("issue_price", ""),
            "币种": it.get("currency", ""),
            "上市日": datetime.fromtimestamp(to_float(it.get("ipo_date")) or 0,
                                            tz=tz).strftime("%Y-%m-%d")
                    if to_float(it.get("ipo_date")) else "",
            "倒计时": it.get("days_to_ipo", ""),
            "简介": str(it.get("description", ""))[:20],
        } for it in items]
        print_display_table(rows, columns=["symbol", "名称", "发行价", "币种", "上市日", "倒计时", "简介"])
        print()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="按阶段列出 IPO 新股")
    parser.add_argument("--stage", default="wait-listing", choices=_STAGES,
                        help="阶段(默认 wait-listing 待上市暗盘)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_ipo_listings(stage=args.stage, output_json=args.output_json)
    except Exception as e:
        print_error("获取 IPO 列表", str(e))
        sys.exit(1)
