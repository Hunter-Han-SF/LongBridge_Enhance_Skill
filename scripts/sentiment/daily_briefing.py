"""每日市场情绪简报(一键聚合多数据源)。

跨模块旗舰脚本: 一次性生成完整市场简报,聚合:
  ① 市场温度(温度/估值/情绪分项)
  ② 热度榜 top(最受关注的个股)
  ③ 涨跌异动 top(波动最大的个股 + 原因)
  ④ 异动信号统计(利多/利空分布)
  ⑤ 期权 P/C 比率(美股:大盘情绪的期权视角,可选)

输出文字版简报,适合每日开盘前/收盘后快速了解市场状态。

用法:
    python daily_briefing.py                  # 默认美股
    python daily_briefing.py --market HK      # 港股
    python daily_briefing.py --market US --no-pc  # 跳过 P/C 比率(加速)
    python daily_briefing.py --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_anomaly,
    get_heat_rank,
    get_market_temp,
    get_option_volume_realtime,
    get_top_movers,
    print_error,
    print_json,
    to_float,
)


def _section(title: str) -> str:
    return f"\n{'─' * 50}\n  {title}\n{'─' * 50}"


def generate_briefing(market: str = "US", include_pc: bool = True, output_json: bool = False) -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    briefing = {"market": market, "generated_at": now, "sections": {}}
    lines = [f"📰 {market} 市场每日简报  ({now})"]
    lines.append("=" * 50)

    # ① 市场温度
    try:
        temp = get_market_temp(market=market)
        briefing["sections"]["market_temp"] = temp
        lines.append(_section("🌡️ 市场温度"))
        t = to_float(temp.get("temperature"))
        emoji = "🔥偏热" if t and t >= 60 else ("❄️偏冷" if t and t < 40 else "🌡️温和")
        lines.append(f"  温度: {t}/100 {emoji}")
        lines.append(f"  估值分位: {temp.get('valuation')}  情绪: {temp.get('sentiment')}")
        lines.append(f"  {temp.get('description','')}")
    except Exception as e:
        lines.append(_section("🌡️ 市场温度"))
        lines.append(f"  获取失败: {str(e)[:40]}")

    # ② 热度榜 top5
    try:
        key = f"hot_all-{market.lower()}"
        rk = get_heat_rank(key=key, count=5)
        briefing["sections"]["heat_rank"] = rk["lists"]
        lines.append(_section("🔥 热度榜 Top 5"))
        for i, item in enumerate(rk["lists"][:5], 1):
            chg = to_float(item.get("chg"))
            chg_str = f"{chg*100:+.2f}%" if chg is not None else ""
            lines.append(f"  {i}. {item.get('symbol','?')} {item.get('name','')[:10]} "
                        f"{item.get('last_done','')} {chg_str}")
    except Exception as e:
        lines.append(_section("🔥 热度榜"))
        lines.append(f"  获取失败: {str(e)[:40]}")

    # ③ 涨跌异动 top5(带新闻)
    try:
        tm = get_top_movers(market=market, sort="hot", count=5)
        briefing["sections"]["top_movers"] = len(tm["events"])
        lines.append(_section("⚡ 涨跌异动 Top 5"))
        for i, ev in enumerate(tm["events"][:5], 1):
            stock = ev.get("stock") or {}
            chg = to_float(stock.get("change"))
            chg_str = f"{chg*100:+.2f}%" if chg is not None else ""
            lines.append(f"  {i}. {stock.get('symbol','?')} {stock.get('name','')[:10]} "
                        f"{chg_str} — {ev.get('alert_reason','')}")
    except Exception as e:
        lines.append(_section("⚡ 涨跌异动"))
        lines.append(f"  获取失败: {str(e)[:40]}")

    # ④ 异动信号统计
    try:
        an = get_anomaly(market=market, count=100)
        changes = an["changes"]
        bull = sum(1 for c in changes if to_float(c.get("emotion")) == 1)
        bear = sum(1 for c in changes if to_float(c.get("emotion")) == 2)
        briefing["sections"]["anomaly"] = {"total": len(changes), "bull": bull, "bear": bear}
        lines.append(_section("📡 异动信号统计"))
        lines.append(f"  总信号: {len(changes)}  利多 🟢 {bull} / 利空 🔴 {bear}")
        if bull + bear > 0:
            ratio = bull / (bull + bear) * 100
            lines.append(f"  多空比: {ratio:.0f}% 利多 / {100-ratio:.0f}% 利空")
    except Exception as e:
        lines.append(_section("📡 异动信号统计"))
        lines.append(f"  获取失败: {str(e)[:40]}")

    # ⑤ 期权 P/C 比率(仅美股,可选)
    if include_pc and market.upper() == "US":
        try:
            # 用 SPY 作为大盘代表
            pc = get_option_volume_realtime("SPY.US")
            briefing["sections"]["pc_ratio"] = pc
            lines.append(_section("📊 大盘期权 P/C 比率 (SPY)"))
            lines.append(f"  Call 成交: {pc.get('call_volume',0):,.0f}")
            lines.append(f"  Put 成交:  {pc.get('put_volume',0):,.0f}")
            ratio = pc.get("pc_ratio")
            if ratio:
                label = "偏空(看跌对冲多)" if ratio > 1 else ("偏多" if ratio < 0.7 else "中性")
                lines.append(f"  P/C 比率: {ratio:.3f} — {label}")
        except Exception as e:
            lines.append(_section("📊 大盘期权 P/C 比率"))
            lines.append(f"  获取失败(可能非美股或 SPY 无数据): {str(e)[:40]}")

    lines.append("\n" + "=" * 50)

    if output_json:
        print_json(briefing)
        return briefing

    print("\n".join(lines))
    return briefing


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="每日市场情绪简报(聚合多数据源)")
    parser.add_argument("--market", default="US", help="市场: HK|US|CN|SG(默认 US)")
    parser.add_argument("--no-pc", action="store_true", dest="no_pc",
                        help="跳过 P/C 比率(加速,或非美股时用)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        generate_briefing(market=args.market, include_pc=not args.no_pc, output_json=args.output_json)
    except Exception as e:
        print_error("生成市场简报", str(e))
        sys.exit(1)
