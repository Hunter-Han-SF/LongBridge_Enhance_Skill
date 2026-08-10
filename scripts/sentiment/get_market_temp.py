"""获取市场情绪温度指数(0-100,越高越乐观)。

对应 Longbridge CLI: market-temp <MARKET> / --history
官方 skill 无此加工分析。

温度指数综合反映市场情绪:
  - temperature(0-100): 综合温度,>70 偏热(贪婪),<30 偏冷(恐惧)
  - valuation: 估值分位
  - sentiment: 情绪分项
  - description: 文字描述(如"温暖且缓慢上升")

两种模式:
  1. 快照(默认): 当前温度 + 估值/情绪分项
  2. 时序(--history): 历史温度曲线,看情绪变化趋势

支持市场: HK | US | CN | SG

用法:
    python get_market_temp.py                  # 港股快照(默认)
    python get_market_temp.py US               # 美股快照
    python get_market_temp.py US --history     # 美股历史温度
    python get_market_temp.py HK --history --start 2026-01-01 --end 2026-08-10
    python get_market_temp.py US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_market_temp,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def _temp_emoji(temp) -> str:
    """温度转表情。"""
    t = to_float(temp)
    if t is None:
        return ""
    if t >= 70:
        return "🔥 偏热(贪婪)"
    if t >= 50:
        return "🌡️ 偏暖"
    if t >= 30:
        return "❄️ 偏凉"
    return "🥶 偏冷(恐惧)"


def fetch_market_temp(
    market: str = "HK",
    history: bool = False,
    start: str | None = None,
    end: str | None = None,
    output_json: bool = False,
) -> dict:
    data = get_market_temp(market=market, history=history, start=start, end=end)

    if history:
        return _history_mode(market, data, output_json)
    return _snapshot_mode(market, data, output_json)


def _snapshot_mode(market: str, data: dict, output_json: bool) -> dict:
    if is_empty(data) or not isinstance(data, dict):
        raise ValueError(f"无 {market} 市场温度数据。")

    temp = to_float(data.get("temperature"))
    result = {
        "market": market,
        "mode": "snapshot",
        "temperature": temp,
        "valuation": to_float(data.get("valuation")),
        "sentiment": to_float(data.get("sentiment")),
        "description": data.get("description"),
        "interpretation": _temp_emoji(temp),
    }

    if output_json:
        print_json(result)
        return result

    print(f"{market} 市场情绪温度")
    print(f"  🌡️ 温度: {temp}/100  {_temp_emoji(temp)}")
    print(f"  📊 估值分位: {data.get('valuation')}")
    print(f"  💭 情绪分项: {data.get('sentiment')}")
    print(f"  📝 描述: {data.get('description')}")
    return result


def _history_mode(market: str, data: list, output_json: bool) -> dict:
    if is_empty(data) or not isinstance(data, list):
        raise ValueError(f"无 {market} 历史温度数据。")

    result = {
        "market": market,
        "mode": "history",
        "points": len(data),
        "series": data,
    }

    if output_json:
        print_json(result)
        return result

    # 简单统计
    temps = [to_float(d.get("temperature")) for d in data if to_float(d.get("temperature")) is not None]
    print(f"{market} 市场温度历史({len(data)} 个点)")
    if temps:
        print(f"  区间: {min(temps)} ~ {max(temps)}  当前: {temps[-1]}")
    print()
    # 取最近若干点展示
    recent = data[-20:] if len(data) > 20 else data
    print_display_table(recent, columns=["date", "temperature", "valuation", "sentiment"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="市场情绪温度指数(0-100)")
    parser.add_argument("market", nargs="?", default="HK",
                        help="市场: HK|US|CN|SG(默认 HK)")
    parser.add_argument("--history", action="store_true", help="历史温度时序(默认快照)")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD(仅 history)")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD(仅 history)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_market_temp(market=args.market, history=args.history,
                          start=args.start, end=args.end, output_json=args.output_json)
    except Exception as e:
        print_error("获取市场温度", str(e))
        sys.exit(1)
