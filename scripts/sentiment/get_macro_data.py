"""宏观经济指标数据(指标发现 + 历史发布记录 + 逊预期/超预期统计)。

对应 Longbridge CLI: macrodata [--keyword] / macrodata <CODE> --start --end
与 get_macro_calendar.py 互补:那个按日期看即将发布,本脚本按指标看历史。

两步式:
  1. 列指标: python get_macro_data.py --keyword CPI --country US
  2. 查历史: python get_macro_data.py --code <indicator_code> --count 24

加工: 每期计算 actual vs forecast 的偏离(surprise),统计超/逊预期比例。

用法:
    python get_macro_data.py                                    # 全部指标(第1页)
    python get_macro_data.py --keyword CPI --country US
    python get_macro_data.py --code 30771936 --count 12         # PCE 历史
    python get_macro_data.py --code 30771936 --start 2024-01-01 --end 2024-12-31
    python get_macro_data.py --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_macro_history,
    get_macro_indicators,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _list_mode(keyword: str | None, country: str | None, page: int,
               output_json: bool) -> dict:
    data = get_macro_indicators(keyword=keyword, country=country, page=page)
    items = data.get("list", [])
    if is_empty(items):
        raise ValueError(f"无匹配指标(keyword={keyword}, country={country}, page={page})。")
    result = {"mode": "list", "count": data.get("count"), "has_more": data.get("has_more"),
              "page": page, "indicators": items}
    if output_json:
        print_json(result)
        return result
    print(f"宏观指标(共 {data.get('count')} 个,第 {page} 页"
          f"{'还有更多' if data.get('has_more') else ',已是最后一页'})")
    print()
    rows = [{
        "indicator_code": i.get("indicator_code", ""),
        "指标": str(i.get("name", ""))[:44],
        "国家": i.get("country", ""),
        "重要性": i.get("importance", ""),
        "频率": i.get("periodicity", ""),
    } for i in items]
    print_display_table(rows, columns=["indicator_code", "指标", "国家", "重要性", "频率"])
    print("\n提示: 用 --code <indicator_code> 查历史发布数据")
    return result


def _history_mode(code: str, count: int, start: str | None, end: str | None,
                  output_json: bool) -> dict:
    rows = get_macro_history(code, start=start, end=end, limit=count)
    if is_empty(rows):
        raise ValueError(f"无历史数据(code={code})。确认 code 来自列表模式输出。")

    # surprise = actual - forecast;超/逊预期统计
    beats = misses = total = 0
    for r in rows:
        a, f = to_float(r.get("actual_value")), to_float(r.get("forecast_value"))
        if a is not None and f is not None:
            r["surprise"] = round(a - f, 4)
            total += 1
            if a > f:
                beats += 1
                r["vs_forecast"] = "超预期"
            elif a < f:
                misses += 1
                r["vs_forecast"] = "逊预期"
            else:
                r["vs_forecast"] = "符合"
        else:
            r["surprise"] = None
            r["vs_forecast"] = "待发布" if a is None else ""
        ts = to_float(r.get("release_at"))
        if ts:
            r["release_date"] = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

    result = {
        "mode": "history",
        "code": code,
        "count": len(rows),
        "beat_rate": round(beats / total, 3) if total else None,
        "stats": {"beats": beats, "misses": misses, "released": total},
        "history": rows,
    }

    if output_json:
        print_json(result)
        return result

    print(f"宏观指标 {code} 历史发布({len(rows)} 期)")
    if total:
        print(f"  超预期 {beats} 次 / 逊预期 {misses} 次(超预期率 {result['beat_rate']:.0%})")
    print()
    table = [{
        "period": r.get("period", ""),
        "前值": r.get("previous_value", ""),
        "预测": r.get("forecast_value", ""),
        "实际": r.get("actual_value", ""),
        "vs预期": r.get("vs_forecast", ""),
        "单位": r.get("unit", ""),
    } for r in rows]
    print_display_table(table, columns=["period", "前值", "预测", "实际", "vs预期", "单位"])
    return result


def fetch_macro_data(
    code: str | None = None,
    keyword: str | None = None,
    country: str | None = None,
    page: int = 1,
    count: int = 12,
    start: str | None = None,
    end: str | None = None,
    output_json: bool = False,
) -> dict:
    if code:
        return _history_mode(code, count, start, end, output_json)
    return _list_mode(keyword, country, page, output_json)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="宏观经济指标(发现+历史)")
    parser.add_argument("--code", default=None, help="指标代码(来自列表输出),查历史")
    parser.add_argument("--keyword", default=None, help="按指标名搜索(列表模式)")
    parser.add_argument("--country", default=None, choices=["HK", "CN", "US", "EU", "JP", "SG"],
                        help="按国家过滤(列表模式)")
    parser.add_argument("--page", type=int, default=1, help="列表模式页码(默认 1)")
    parser.add_argument("--count", type=int, default=12, help="历史期数(默认 12)")
    parser.add_argument("--start", default=None, help="历史开始日期 YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="历史结束日期 YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_macro_data(code=args.code, keyword=args.keyword, country=args.country,
                         page=args.page, count=args.count, start=args.start, end=args.end,
                         output_json=args.output_json)
    except Exception as e:
        print_error("获取宏观数据", str(e))
        sys.exit(1)
