"""财报 IV Crush(隐含波动率塌陷)分析。

⚠️ 关键依赖:本脚本依赖 get_iv_history.py 的本地 IV 累积数据(同 IV Rank)。
   Longbridge 不提供历史 IV,靠每日累积。建议配 cron 每日运行 get_iv_history。

IV Crush 现象:
  财报发布前,市场不确定性推高 IV(期权变贵);财报落地后不确定性消除,
  IV 急剧下降(可能跌 20-50%),即使股价没动,期权买方也会因 IV 下跌而亏损。
  这是期权卖方的经典策略:财报前卖高 IV 期权,财报后 IV 回落获利。

本脚本做两件事:
  1. 定位最近/下一次财报日(从 earnings-calendar)
  2. 分析当前 IV 相对历史的位置 + 财报前后的 IV 变化参考

用法:
    python analyze_iv_crush.py AAPL.US
    python analyze_iv_crush.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_finance_calendar,
    get_underlying_price,
    print_error,
    print_json,
    to_float,
)


def _load_iv_history(symbol: str) -> list[dict]:
    """加载本地 IV 历史(复用 get_iv_history 的存储格式)。"""
    from pathlib import Path
    hist_dir = Path.home() / ".lbr_iv_history"
    safe = symbol.replace(".", "_").replace("/", "_")
    path = hist_dir / f"{safe}.json"
    if not path.is_file():
        return []
    import json
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _counter_code(counter_id: str) -> str:
    """取 counter_id 末段代码:'ST/US/AAPL' → 'AAPL'。"""
    parts = str(counter_id).split("/")
    return parts[-1].upper() if parts else ""


def find_next_earnings(symbol: str, lookforward_days: int = 120) -> dict | None:
    """从财报日历找最近一次财报(已公布或未来)。

    ⚠️ Longbridge 的 finance-calendar report 在传 --symbol 单标的过滤时,
       默认返回最近一次财报(通常是刚发布的),传 --start 反而查不到。
       因此这里不传 start,拿 API 默认锚点,再由 published 字段判断状态。
    """
    ticker = symbol.split(".")[0]
    market = symbol.split(".")[-1] if "." in symbol else "US"

    buckets = get_finance_calendar(
        category="report", market=market, symbol=symbol, count=50,
    )
    for b in buckets:
        for info in b.get("infos", []):
            cid = info.get("counter_id", "")
            # 精确匹配标的代码(不能用子串:单字母 ticker 如 "A" 会误匹配 AAPL)
            if _counter_code(cid) != ticker.upper():
                continue
            ext = info.get("ext") or {}
            kv_list = info.get("data_kv", []) if isinstance(info.get("data_kv"), list) else []
            kv = {k.get("type"): k.get("value_raw", "") for k in kv_list if isinstance(k, dict)}
            return {
                "date": info.get("date", ""),
                "date_type": info.get("date_type", ""),
                "published": bool(kv.get("actual_eps") or kv.get("actual_revenue")),
                "estimate_eps": kv.get("estimate_eps", ""),
                "actual_eps": kv.get("actual_eps", ""),
                "content": info.get("content", ""),
            }
    return None


def _get_current_iv(symbol: str) -> float | None:
    """取当前 ATM IV(复用 get_iv_history 的逻辑)。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from get_iv_history import get_current_atm_iv  # noqa: E402
        iv, _ = get_current_atm_iv(symbol)
        return iv
    except Exception:
        return None


def analyze_iv_crush(symbol: str, output_json: bool = False) -> dict:
    # 1. 财报日
    earnings = find_next_earnings(symbol)
    # 2. 当前 IV
    current_iv = _get_current_iv(symbol)
    # 3. 历史 IV
    history = _load_iv_history(symbol)

    # 分析历史 IV 的财报效应:找历史中 IV 峰值后的回落幅度
    # ⚠️ (iv, 历史记录) 必须成对遍历,不能先过滤出 IV 列表再按下标回查 history
    #    (否则存在无效记录时日期会错位)
    crush_examples = []
    if len(history) >= 10:
        pairs = [(h, to_float(h.get("atm_iv_pct"))) for h in history]
        pairs = [(h, v) for h, v in pairs if v and v > 0]
        # 找 IV 突然下降的日子(可能是财报后)
        for i in range(5, len(pairs)):
            h_prev, iv_prev = pairs[i - 1]
            h_cur, iv_cur = pairs[i]
            if iv_prev > 0 and iv_cur < iv_prev * 0.8:  # 跌超 20%
                crush_examples.append({
                    "date": h_cur.get("date"),
                    "before_iv": iv_prev,
                    "after_iv": iv_cur,
                    "drop_pct": round((1 - iv_cur / iv_prev) * 100, 1),
                })

    # 当前 IV 分位
    iv_percentile = None
    iv_rank_label = ""
    if history and current_iv:
        ivs = [to_float(h.get("atm_iv_pct")) for h in history]
        ivs = [v for v in ivs if v and v > 0]
        if ivs:
            below = sum(1 for v in ivs if v < current_iv * 100)
            iv_percentile = round(below / len(ivs) * 100, 1)
            if iv_percentile > 70:
                iv_rank_label = "偏高(财报前常见,卖方机会)"
            elif iv_percentile < 30:
                iv_rank_label = "偏低"
            else:
                iv_rank_label = "中位"

    result = {
        "symbol": symbol,
        "current_iv_pct": round(current_iv * 100, 2) if current_iv else None,
        "iv_percentile": iv_percentile,
        "iv_rank_label": iv_rank_label,
        "next_earnings": earnings,
        "history_points": len(history),
        "historical_crush_examples": crush_examples[-3:] if crush_examples else [],
        "note": "IV Crush 分析需 get_iv_history 累积数据。历史 crush 示例依赖 IV 序列,"
                "数据不足时该字段为空。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} IV Crush 分析")
    print()
    print(f"当前 ATM IV: {round(current_iv * 100, 2) if current_iv else 'N/A'}%", end="")
    if iv_percentile is not None:
        print(f"  (历史分位 {iv_percentile}% — {iv_rank_label})")
    else:
        print("  (历史数据不足,无法算分位)")

    print()
    if earnings:
        status = "✅ 已发布" if earnings["published"] else "⏳ 待发布"
        print(f"最近财报: {earnings['date']} {earnings.get('date_type','')} {status}")
        if earnings.get("estimate_eps"):
            print(f"  预测 EPS: {earnings['estimate_eps']}")
        if earnings.get("actual_eps"):
            print(f"  实际 EPS: {earnings['actual_eps']}")
    else:
        print("最近财报: 未在日历中找到(可能无近期财报)")

    print()
    if crush_examples:
        print(f"历史 IV Crush 示例(IV 单日跌幅 >20% 的日子,共 {len(crush_examples)} 次):")
        for ex in crush_examples[-3:]:
            print(f"  {ex['date']}: {ex['before_iv']}% → {ex['after_iv']}% (跌 {ex['drop_pct']}%)")
    elif history:
        print("历史 IV Crush: 数据不足以检测(需更多累积,建议每日运行 get_iv_history)")
    else:
        print("历史 IV Crush: 无本地 IV 历史数据")
        print("  → 先运行: python get_iv_history.py " + symbol)
        print("  → 建议配 cron 每日运行,积累 ≥20 天后分析更准")

    print()
    # 策略提示
    if earnings and not earnings["published"] and iv_percentile and iv_percentile > 60:
        print("💡 策略参考: 财报待发布 + IV 偏高 → 可考虑财报前卖出期权(卖高 IV),"
              "赌财报后 IV 回落。但需注意财报方向风险。")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="财报 IV Crush 分析")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze_iv_crush(args.symbol, output_json=args.output_json)
    except Exception as e:
        print_error("IV Crush 分析", str(e))
        sys.exit(1)
