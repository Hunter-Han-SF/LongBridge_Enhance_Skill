"""获取沽空(做空)数据:日成交量比率 + 未平仓持仓。

对应 Longbridge CLI: short-trades / short-positions <SYMBOL>
官方 skill 无此加工分析。

两种数据:
  1. trades(默认): 每日沽空成交量 + 沽空比率(沽空占总成交比例)
     - 反映当日做空活跃度。比率持续走高 = 看空情绪升温
  2. positions(--position): 沽空未平仓量(持仓)
     - 美股(双周FINRA): current_shares_short / days_to_cover(回补天数)
     - 港股(日频HKEX): 未平仓股数 / cost(平均沽空成本)
     - days_to_cover 高 = 空头难回补,逼空风险大

字段差异(自动识别市场):
  美股 trades:  nus_amount/ny_amount/total_amount/rate/close
  港股 trades:  amount/balance/total_amount/rate/close
  美股 positions: current_shares_short/days_to_cover/rate/close
  港股 positions: amount/balance/cost/rate/close

用法:
    python get_short_sale.py AAPL.US                  # 日沽空成交量
    python get_short_sale.py AAPL.US --position       # 沽空持仓
    python get_short_sale.py AAPL.US --count 30
    python get_short_sale.py 700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_short_positions,
    get_short_trades,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
    to_int,
)


def _ts_to_date(ts) -> str:
    """Unix 时间戳 → YYYY-MM-DD(键名标注 UTC,避免与市场当地时间混淆)。"""
    n = to_int(ts)
    if n is None:
        return str(ts)
    return datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%d")


def _rate_label(rate: float) -> str:
    """沽空比率解读。"""
    if rate is None:
        return ""
    pct = rate * 100
    if pct >= 40:
        return f"{pct:.1f}% 🔴(做空极活跃)"
    if pct >= 25:
        return f"{pct:.1f}% 🟠(做空较活跃)"
    if pct >= 10:
        return f"{pct:.1f}% 🟡(有一定做空)"
    return f"{pct:.1f}% 🟢(做空清淡)"


def fetch_short_sale(
    symbol: str,
    position: bool = False,
    count: int = 20,
    output_json: bool = False,
) -> dict:
    if position:
        return _position_mode(symbol, count, output_json)
    return _trade_mode(symbol, count, output_json)


def _trade_mode(symbol: str, count: int, output_json: bool) -> dict:
    data = get_short_trades(symbol, count=count)
    rows = data["data"]
    market = data.get("market")
    if is_empty(rows):
        raise ValueError(f"无沽空成交量数据。确认 {symbol} 支持沽空查询。")

    # 加工可读列(日期键名带 _utc 后缀,明确时区)
    for r in rows:
        r["date_utc"] = _ts_to_date(r.get("timestamp"))
        r["rate_label"] = _rate_label(to_float(r.get("rate")))

    # 趋势判断: 最近 vs 前1/3 平均
    rates = [to_float(r.get("rate")) or 0 for r in rows]
    recent = sum(rates[-3:]) / min(3, len(rates)) if rates else 0
    earlier = sum(rates[:max(1, len(rates) // 3)]) / max(1, len(rates) // 3) if rates else 0
    if recent > earlier * 1.2:
        trend = "↑ 沽空比率走高(看空升温)"
    elif recent < earlier * 0.8:
        trend = "↓ 沽空比率走低(看空降温)"
    else:
        trend = "→ 沽空比率平稳"

    result = {
        "symbol": symbol,
        "mode": "trades",
        "market": market,
        "points": len(rows),
        "trend": trend,
        "latest_rate": rates[-1] if rates else None,
        "data": rows,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 日沽空成交量({market}市场,{len(rows)} 个交易日)")
    print(f"  趋势: {trend}")
    print(f"  最新沽空比率: {_rate_label(rates[-1] if rates else None)}")
    print()
    # 列因市场而异
    if market == "US":
        cols = ["date_utc", "rate_label", "nus_amount", "ny_amount", "total_amount", "close"]
    else:  # HK
        cols = ["date_utc", "rate_label", "amount", "total_amount", "close"]
    print_display_table(rows, columns=cols)
    return result


def _position_mode(symbol: str, count: int, output_json: bool) -> dict:
    data = get_short_positions(symbol, count=count)
    rows = data["data"]
    market = data.get("market")
    if is_empty(rows):
        raise ValueError(f"无沽空持仓数据。确认 {symbol} 支持沽空查询。")

    for r in rows:
        r["date_utc"] = _ts_to_date(r.get("timestamp"))

    result = {
        "symbol": symbol,
        "mode": "positions",
        "market": market,
        "update_timestamp": data.get("update_timestamp"),
        "points": len(rows),
        "data": rows,
    }

    if output_json:
        print_json(result)
        return result

    freq = "双周(FINRA)" if market == "US" else "日频(HKEX)"
    print(f"{symbol} 沽空未平仓持仓({market}市场,{freq},{len(rows)} 期)")
    print()
    if market == "US":
        # days_to_cover 解读
        latest_dtc = to_float(rows[-1].get("days_to_cover"))
        if latest_dtc is not None:
            if latest_dtc >= 5:
                print(f"  ⚠️ days_to_cover={latest_dtc} ≥5,逼空风险偏高")
            else:
                print(f"  days_to_cover={latest_dtc},回补压力正常")
        cols = ["date_utc", "current_shares_short", "rate", "days_to_cover", "close"]
    else:  # HK
        cols = ["date_utc", "amount", "balance", "rate", "cost", "close"]
    print()
    print_display_table(rows, columns=cols)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="沽空数据(成交量比率 + 未平仓持仓)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 700.HK")
    parser.add_argument("--position", action="store_true",
                        help="查沽空未平仓持仓(默认查日成交量)")
    parser.add_argument("--count", type=int, default=20, help="返回期数(默认 20)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_short_sale(args.symbol, position=args.position,
                         count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("获取沽空数据", str(e))
        sys.exit(1)
