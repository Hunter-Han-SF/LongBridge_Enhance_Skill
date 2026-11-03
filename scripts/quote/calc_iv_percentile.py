"""IV Percentile(隐含波动率百分位,B 档·基于本地累积序列)。

对应 Futu: get_option_underlying_overview(IV_PERCENTILE 字段)

⚠️ Longbridge 不直接提供。依赖 get_iv_history 本地累积序列(建议 ≥ 20 点)。

IV Percentile = 历史中 IV 低于当前 IV 的天数占比 × 100
与 IV Rank 区别:Percentile 对异常值不敏感(用占比),Rank 对极端值敏感(用极差)。

用法:
    python calc_iv_percentile.py AAPL.US
    python calc_iv_percentile.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import print_error, print_json  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from get_iv_history import comparable_iv_series, iv_history as _build_series  # noqa: E402


def calc_iv_percentile(symbol: str, min_points: int = 20, output_json: bool = False) -> dict:
    hist = _build_series(symbol, append=True, output_json=False, quiet=True)
    if not hist.get("appended_today", False):
        raise ValueError("无法采集当前恒定30日 IV，历史样本保留")
    if min_points < 2:
        raise ValueError("至少需要两个可比 IV 样本")
    series = comparable_iv_series(hist.get("series", []))
    observation = hist.get("observed_at")
    if observation:
        observed_day = observation[:10]
        series = [row for row in series if row["date"] <= observed_day]
        if not series or series[-1]["date"] != observed_day:
            raise ValueError("当前观测日没有有效的恒定30日 IV 样本")
    if len(series) < min_points:
        raise ValueError(
            f"历史 IV 数据不足(仅 {len(series)} 点,需 ≥ {min_points})。"
            f"请多运行 get_iv_history.py 积累数据。"
        )

    ivs = [s["atm_iv_pct"] for s in series]
    current = ivs[-1]
    below = sum(1 for v in ivs[:-1] if v < current)
    total = len(ivs) - 1
    percentile = (below / total * 100) if total > 0 else 50.0

    # 中位数(偶数长度取中间两值平均)
    sv = sorted(ivs)
    n = len(sv)
    median = sv[n // 2] if n % 2 == 1 else (sv[n // 2 - 1] + sv[n // 2]) / 2

    result = {
        "symbol": symbol,
        "current_iv_pct": current,
        "observed_at": series[-1].get("observed_at"),
        "quote_freshness": "unknown",
        "iv_percentile": round(percentile, 1),
        "data_points": len(series),
        "date_range": f"{series[0]['date']} ~ {series[-1]['date']}",
        "median_iv_pct": round(median, 2),
        "interpretation": (
            "高位(>70): 样本分位较高"
            if percentile > 70 else
            "低位(<30): 样本分位较低"
            if percentile < 30 else
            "中位(30-70)"
        ),
        "method": "历史中 IV < 当前 IV 的天数 / 总天数 × 100",
        "note": "Longbridge 不直接提供 IV Percentile,基于本地累积序列计算",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} IV Percentile(本地累积 {len(series)} 点,{hist['date_range']})")
    if result["observed_at"]:
        print(f"  观测时间: {result['observed_at']}，行情新鲜度未知")
    print(f"  当前 IV:        {current}%")
    print(f"  中位 IV:        {result['median_iv_pct']}%")
    print(f"  IV Percentile:  {result['iv_percentile']}  → {result['interpretation']}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IV Percentile(基于本地累积 IV 序列)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--min-points", type=int, default=20, help="最少数据点数(默认 20)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        calc_iv_percentile(args.symbol, min_points=args.min_points, output_json=args.output_json)
    except Exception as e:
        print_error("IV Percentile", str(e))
        sys.exit(1)
