"""IV Rank(隐含波动率排名,B 档·基于本地累积序列)。

对应 Futu: get_option_underlying_overview(IV_RANK 字段)

⚠️ Longbridge 不直接提供历史 IV / IV Rank。本脚本依赖 get_iv_history 的本地累积序列。
   首次运行需先用 get_iv_history.py 积累数据(建议 ≥ 20 个交易日)。

IV Rank = (当前IV - 最低IV) / (最高IV - 最低IV) × 100

用法:
    python calc_iv_rank.py AAPL.US
    python calc_iv_rank.py AAPL.US --json
    python calc_iv_rank.py AAPL.US --min-points 20  # 数据不足时报错而非勉强计算
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import print_error, print_json  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from get_iv_history import iv_history as _build_series  # noqa: E402


def calc_iv_rank(symbol: str, min_points: int = 20, output_json: bool = False) -> dict:
    hist = _build_series(symbol, append=True, output_json=False, quiet=True)
    series = hist["series"]
    if len(series) < min_points:
        raise ValueError(
            f"历史 IV 数据不足(仅 {len(series)} 点,需 ≥ {min_points})。"
            f"请多运行 get_iv_history.py 积累数据。当前已记录: "
            f"{hist['date_range']}"
        )

    ivs = [s["atm_iv_pct"] for s in series]
    current = ivs[-1]
    hi, lo = max(ivs), min(ivs)
    rank = ((current - lo) / (hi - lo) * 100) if hi > lo else 50.0

    result = {
        "symbol": symbol,
        "current_iv_pct": current,
        "iv_rank": round(rank, 1),
        "data_points": len(series),
        "date_range": hist["date_range"],
        "iv_high_pct": hi,
        "iv_low_pct": lo,
        "interpretation": (
            "高位(>70): IV 偏贵,可考虑卖权策略"
            if rank > 70 else
            "低位(<30): IV 偏便宜,可考虑买权策略"
            if rank < 30 else
            "中位(30-70): IV 适中"
        ),
        "method": "(当前IV - 最低IV) / (最高IV - 最低IV) × 100",
        "note": "Longbridge 不直接提供 IV Rank,基于 get_iv_history 本地累积序列计算",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} IV Rank(本地累积 {len(series)} 点,{hist['date_range']})")
    print(f"  当前 IV:   {current}%")
    print(f"  区间 IV:   {lo}% ~ {hi}%")
    print(f"  IV Rank:   {result['iv_rank']}  → {result['interpretation']}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IV Rank(基于本地累积 IV 序列)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--min-points", type=int, default=20, help="最少数据点数(默认 20)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        calc_iv_rank(args.symbol, min_points=args.min_points, output_json=args.output_json)
    except Exception as e:
        print_error("IV Rank", str(e))
        sys.exit(1)
