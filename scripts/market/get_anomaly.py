"""获取异动信号(大单买卖/封板/放量等)。

对应 Longbridge CLI: anomaly --market --symbol --count
官方 skill 无此能力的加工分析。

返回的 changes 含:
  - alert_name: 异动类型中文名(大笔买入/大笔卖出/封涨停/封跌停/竞价异动...)
  - alert_type: 类型编号(5=大笔买入,6=大笔卖出,等)
  - emotion: 情绪方向 1=利多, 2=利空
  - counter_id: 标的内部 ID(如 ST/US/DASH),可转标准 symbol
  - name: 标的中文名
  - change_values: 异动描述(如 ["800 股"])
  - alert_time: Unix 时间戳

用法:
    python get_anomaly.py                      # 默认港股全市场
    python get_anomaly.py --market US          # 美股
    python get_anomaly.py --market US --count 30
    python get_anomaly.py --market HK --symbol 700.HK  # 单标的过滤
    python get_anomaly.py --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    counter_id_to_symbol,
    get_anomaly,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_int,
)

# alert_type 编号 → 含义(实测归纳,供参考)
ALERT_TYPE_MAP = {
    5: "大笔买入",
    6: "大笔卖出",
    11: "价格波动异动",
    13: "竞价异动",
    27: "封涨停",
    28: "封跌停",
}


def _ts_to_time(ts) -> str:
    """Unix 时间戳 → HH:MM:SS(标注 UTC,避免与当地时间混淆)。"""
    n = to_int(ts)
    if n is None:
        return str(ts)
    return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%H:%M:%S") + " UTC"


def _emotion_label(emotion) -> str:
    """emotion 1=利多 2=利空,转可读标签。"""
    e = to_int(emotion)
    if e == 1:
        return "利多 🟢"
    if e == 2:
        return "利空 🔴"
    return "中性 ⚪"


def fetch_anomaly(
    market: str = "HK",
    symbol: str | None = None,
    count: int = 50,
    output_json: bool = False,
) -> dict:
    data = get_anomaly(market=market, symbol=symbol, count=count)
    changes = data["changes"]

    # 加工:转 symbol、加可读列
    for ch in changes:
        ch["symbol"] = counter_id_to_symbol(ch.get("counter_id", "")) or ch.get("counter_id", "")
        ch["emotion_label"] = _emotion_label(ch.get("emotion"))
        ch["alert_time_str"] = _ts_to_time(ch.get("alert_time"))
        ch["type_label"] = ALERT_TYPE_MAP.get(to_int(ch.get("alert_type")), ch.get("alert_name", ""))

    result = {
        "market": market,
        "symbol_filter": symbol,
        "all_off": data["all_off"],
        "count": len(changes),
        "note": "all_off=True 表示当前无任何异动信号" if data["all_off"] else None,
        "changes": changes,
    }

    if output_json:
        print_json(result)
        return result

    if data["all_off"]:
        print(f"{market} 市场:当前无任何异动信号(all_off=True)")
        return result

    if is_empty(changes):
        print(f"{market} 市场:无异动数据。")
        return result

    scope = f"标的 {symbol}" if symbol else f"{market} 全市场"
    print(f"{scope} 异动信号({len(changes)} 条,时间 {changes[0].get('alert_time_str') if changes else '-'})")
    print()
    cols = ["alert_time_str", "symbol", "name", "alert_name", "emotion_label", "change_values"]
    print_display_table(changes, columns=cols)
    print()
    # 利多/利空统计
    bull = sum(1 for c in changes if to_int(c.get("emotion")) == 1)
    bear = sum(1 for c in changes if to_int(c.get("emotion")) == 2)
    print(f"情绪分布: 利多 {bull} 🟢 / 利空 {bear} 🔴")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="获取异动信号(大单/封板/放量等)")
    parser.add_argument("--market", default="HK", help="市场: HK|US|CN|SG(默认 HK)")
    parser.add_argument("--symbol", default=None, help="过滤特定标的,如 700.HK")
    parser.add_argument("--count", type=int, default=50, help="返回条数(≤100,默认 50)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_anomaly(market=args.market, symbol=args.symbol,
                      count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取异动信号", str(e))
        sys.exit(1)
