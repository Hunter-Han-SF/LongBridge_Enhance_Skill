"""获取沽空(做空)数据:日成交量比率 + 未平仓持仓。

对应 Longbridge CLI: short-trades / short-positions <SYMBOL>
官方 skill 无此加工分析。

两种数据:
  1. trades(默认): 每日沽空成交量 + 沽空比率(沽空占总成交比例)
     - 反映当日做空活跃度。比率持续走高表示沽空成交占比增加
  2. positions(--position): 沽空未平仓量(持仓)
     - 美股(双周FINRA): current_shares_short / days_to_cover(回补天数)
     - 港股(日频HKEX): 未平仓股数 / cost(平均沽空成本)
     - days_to_cover 高 = 空头难回补,逼空风险大

⚠️ 两个市场的 rate 含义不同,解读也不同:
  - 港股: HKEX 披露的卖空成交额 / 总成交额,按 40% / 25% / 10% 分档解读
  - 美股: FINRA 每日空头成交报告里带空头标记的成交量 / 总成交量,含做市商对冲和提供
    流动性的空头成交;每只股票有自己的常态水平(2026-11 实测 17%~58%),绝对高低不代表
    看空情绪 —— 只报数值、与此前均值比较,不套港股阈值。空头持仓看 --position
    (FINRA 双周 short interest / days_to_cover)。

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


US_BASELINE_MIN_POINTS = 3  # 美股:此前至少有这么多天有效 rate,才与自身均值比较

# 两个市场 rate 的口径,写进输出提醒使用者
RATIO_BASIS = {
    "US": ("FINRA 每日空头成交报告: 带空头标记的成交量 / 总成交量,含做市商对冲与提供流动性的"
           "空头成交;各股有自身的常态水平(实测 17%~58%),绝对高低不代表看空情绪,"
           "rate_label 只与此前均值比较(偏离 20% 以上才记高/低)。"
           "空头持仓看 --position(FINRA 双周 short interest / days_to_cover)"),
    "HK": "HKEX 披露的卖空成交额 / 总成交额;rate_label 按 40% / 25% / 10% 分档",
}


def _rate_label(rate: float, market: str | None = None, baseline: float | None = None) -> str:
    """沽空比率解读。

    港股(HKEX 卖空成交占比)按 40 / 25 / 10 阈值分档。美股(FINRA 空头成交量占比)含做市
    对冲,各股常态水平不同,阈值没有意义:只报数值,并与此前均值 baseline 比较
    (偏离 20% 以上才记高/低);没有基线时只报数值。
    """
    if rate is None:
        return ""
    pct = rate * 100
    if market == "US":
        if baseline is None or baseline <= 0:
            return f"{pct:.1f}%"
        base_pct = baseline * 100
        relation = "高于" if pct > base_pct * 1.2 else "低于" if pct < base_pct * 0.8 else "接近"
        return f"{pct:.1f}%({relation}此前均值 {base_pct:.1f}%)"
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

    is_us = market == "US" or (market is None and str(symbol).upper().endswith(".US"))
    label_market = "US" if is_us else market
    rows = sorted(rows, key=lambda r: to_float(r.get("timestamp")) or 0)
    seen_rates: list[float] = []  # 当前行之前的有效 rate;美股用它作自身基线
    for r in rows:
        r["date_utc"] = _ts_to_date(r.get("timestamp"))
        rate = to_float(r.get("rate"))
        baseline = None
        if is_us and len(seen_rates) >= US_BASELINE_MIN_POINTS:
            baseline = sum(seen_rates) / len(seen_rates)
        r["rate_label"] = _rate_label(rate, label_market, baseline)
        if is_us:
            r["prior_mean_rate"] = round(baseline, 4) if baseline is not None else None
        if rate is not None:
            seen_rates.append(rate)

    rates = [to_float(r.get("rate")) for r in rows]
    timestamps = [to_float(r.get("timestamp")) for r in rows]
    dated = all(t is not None and t > 0 for t in timestamps)
    latest = rates[-1] if dated else None
    term = "空头成交占比" if is_us else "沽空比率"
    trend = f"数据不足，无法判断{term}趋势"
    distinct_dates = len({r["date_utc"] for r in rows}) == len(rows)
    if len(rates) >= 6 and dated and distinct_dates:
        recent = rates[-3:]
        earlier = rates[:max(3, len(rates) // 3)]
        earlier_valid = [r for r in earlier if r is not None]
        if all(r is not None for r in recent) and len(earlier_valid) >= max(3, (len(earlier) + 1) // 2):
            recent_avg = sum(recent) / len(recent)
            earlier_avg = sum(earlier_valid) / len(earlier_valid)
            if recent_avg > earlier_avg * 1.2:
                trend = f"↑ {term}走高"
            elif recent_avg < earlier_avg * 0.8:
                trend = f"↓ {term}走低"
            else:
                trend = f"→ {term}平稳"

    result = {
        "symbol": symbol,
        "mode": "trades",
        "market": market,
        "points": len(rows),
        "trend": trend,
        "latest_rate": latest,
        "ratio_basis": RATIO_BASIS["US" if is_us else "HK"],
        "valid_rate_points": sum(rate is not None for rate in rates),
        "data": rows,
    }

    if output_json:
        print_json(result)
        return result

    title = "日空头成交量(FINRA)" if is_us else "日沽空成交量"
    print(f"{symbol} {title}({market}市场,{len(rows)} 个交易日)")
    print(f"  趋势: {trend}")
    print(f"  最新{term}: "
          f"{_rate_label(latest, label_market, rows[-1].get('prior_mean_rate')) or 'N/A'}")
    if is_us:
        print("  注: 美股空头成交占比 = FINRA 每日空头成交报告里带空头标记的成交量 / 总成交量,"
              "含做市商对冲与提供流动性的空头成交;")
        print("      各股有自身的常态水平,绝对高低不代表看空情绪,上表只与此前均值比较。"
              "空头持仓请用 --position(FINRA 双周 short interest / days_to_cover)")
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
        dated_rows = [r for r in rows if to_float(r.get("timestamp"))]
        latest_row = max(dated_rows, key=lambda r: to_float(r["timestamp"])) if dated_rows else {}
        latest_dtc = to_float(latest_row.get("days_to_cover"))
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
