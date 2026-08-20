"""相对强度与 Beta(对比大盘/任意基准)。

相对强度(Relative Strength)是跑赢/跑输大盘的经典判据:
  RS = 标的区间收益 - 基准区间收益
正 RS 持续扩大 = 强于大盘(资金偏好),负 RS = 弱于大盘。
Beta 衡量对大盘的弹性(>1 放大波动,<1 防御)。

默认基准:美股 SPY,可换 .VIX.US(做空对冲用)等任意标的;
港股建议 0700.HK 或用恒指 ETF,A 股用 510300.SH。

用法:
    python calc_relative_strength.py AAPL.US
    python calc_relative_strength.py NVDA.US --benchmark QQQ.US
    python calc_relative_strength.py 0700.HK --benchmark 2800.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    get_kline_adjusted,
    print_display_table,
    print_error,
    print_json,
    to_float,
)
from indicators import beta, daily_returns, total_return  # noqa: E402

# 各市场默认基准
DEFAULT_BENCHMARK = {"US": "SPY.US", "HK": "2800.HK", "SH": "510300.SH", "SZ": "510300.SH"}


def _ts_to_date(ts) -> str:
    try:
        n = int(float(ts))
        if n > 1e12:
            n //= 1000
        return datetime.utcfromtimestamp(n).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return str(ts)


def analyze(symbol: str, benchmark: str | None = None, count: int = 260,
            output_json: bool = False) -> dict:
    if benchmark is None:
        market = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else "US"
        benchmark = DEFAULT_BENCHMARK.get(market, "SPY.US")

    kl_a = get_kline_adjusted(symbol, count=count)
    kl_b = get_kline_adjusted(benchmark, count=count)
    if not kl_a or not kl_b:
        raise ValueError(f"无法获取 {symbol} 或基准 {benchmark} 的 K 线")

    def _series(kl):
        return [(str(k.get("time") or k.get("timestamp") or i), to_float(k.get("close")))
                for i, k in enumerate(kl)]

    a = [(t, c) for t, c in _series(kl_a) if c]
    b = [(t, c) for t, c in _series(kl_b) if c]

    # 按日期对齐(取交集;time 可能是 ISO 字符串或时间戳,统一转日期键)
    def _datekey(t):
        return t[:10] if "-" in t or "/" in t else _ts_to_date(t)

    b_map = {_datekey(t): c for t, c in b}
    pairs = [(_datekey(t), ca, b_map[_datekey(t)]) for t, ca in a if _datekey(t) in b_map]
    if len(pairs) < 40:
        raise ValueError(f"与基准可对齐的 K 线不足({len(pairs)} 根,需 ≥40)")

    dates = [p[0] for p in pairs]
    closes_a = [p[1] for p in pairs]
    closes_b = [p[2] for p in pairs]

    windows = {"1周": 5, "1月": 21, "3月": 63, "6月": 126, "1年": 252}
    rows = []
    rs_all = {}
    for name, n in windows.items():
        if len(closes_a) > n and len(closes_b) > n:
            ra = (closes_a[-1] / closes_a[-n - 1] - 1) * 100
            rb = (closes_b[-1] / closes_b[-n - 1] - 1) * 100
            rs = ra - rb
            rs_all[name] = rs
            rows.append({"周期": name, "标的收益": f"{ra:+.1f}%",
                         "基准收益": f"{rb:+.1f}%", "相对强度": f"{rs:+.1f}%"})

    rets_a = daily_returns(closes_a)
    rets_b = daily_returns(closes_b)
    bta = beta(rets_a, rets_b)

    # 综合判断:多个周期 RS 同向为正/负
    vals = list(rs_all.values())
    if len(vals) >= 3 and sum(1 for v in vals if v > 0) >= len(vals) - 1:
        verdict = "持续跑赢大盘(强势股)"
    elif len(vals) >= 3 and sum(1 for v in vals if v < 0) >= len(vals) - 1:
        verdict = "持续跑输大盘(弱势股)"
    else:
        verdict = "与大盘互有强弱(震荡)"
    beta_note = (f"Beta={bta:.2f}(每 1% 大盘波动,标的约 {bta:+.2f}%)"
                 if bta else "Beta 数据不足")
    if bta:
        beta_note += " 高弹性" if bta > 1.3 else (" 防御型" if bta < 0.7 else "")

    result = {
        "symbol": symbol,
        "benchmark": benchmark,
        "aligned_bars": len(pairs),
        "date_range": f"{dates[0]} ~ {dates[-1]}",
        "relative_strength": rs_all,
        "beta": round(bta, 3) if bta else None,
        "verdict": verdict,
        "beta_note": beta_note,
        "table": rows,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 相对强度(基准 {benchmark},对齐 {len(pairs)} 根日K)")
    print_display_table(rows, columns=["周期", "标的收益", "基准收益", "相对强度"])
    print()
    print(f"  判断: {verdict}")
    print(f"  {beta_note}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="相对强度 vs 大盘/基准 + Beta")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US")
    parser.add_argument("--benchmark", default=None,
                        help="基准(默认按市场: US=SPY / HK=2800 / SH,SZ=510300)")
    parser.add_argument("--count", type=int, default=260, help="K 线根数(默认 260)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, benchmark=args.benchmark, count=args.count,
                output_json=args.output_json)
    except Exception as e:
        print_error("相对强度", str(e))
        sys.exit(1)
