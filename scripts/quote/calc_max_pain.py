"""Max Pain(最大痛点)——期权到期时让买方整体损失最大的行权价。

理论: 做市商/卖方的对冲行为倾向于把价格"拉"向 Max Pain 价位
  (该价位上所有 Call+Put 的内在价值赔付总和最小)。
到期日效应: 越接近到期,价格向 Max Pain 收敛的引力越常被观察到。

⚠️ 近似说明: 标准算法用 OI(未平仓量)加权;Longbridge chain 无按行权价的 OI,
   本脚本用成交量(call_vol/put_vol)代理,流动性好的标的近似度较高。

用法:
    python calc_max_pain.py AAPL.US --date 2026-09-18
    python calc_max_pain.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_option_chain,
    get_option_expirations,
    get_underlying_price,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def analyze(symbol: str, date: str | None = None, output_json: bool = False) -> dict:
    price = get_underlying_price(symbol)
    if not price:
        raise ValueError(f"无法获取 {symbol} 现价")
    if date is None:
        exps = get_option_expirations(symbol)
        if not exps:
            raise ValueError(f"{symbol} 无可用到期日")
        date = exps[0]

    chain = get_option_chain(symbol, date)
    if is_empty(chain):
        raise ValueError(f"{symbol} 在 {date} 无期权链")

    strikes = []
    for r in chain:
        s = to_float(r.get("strike"))
        cv = to_float(r.get("call_vol"), 0) or 0
        pv = to_float(r.get("put_vol"), 0) or 0
        if s and (cv > 0 or pv > 0):
            strikes.append((s, cv, pv))
    if not strikes:
        raise ValueError("链上无有效成交量数据")

    # 对每个候选结算价 S,计算总赔付 = Σ max(S-K,0)·call_vol + Σ max(K-S,0)·put_vol
    candidates = sorted({s for s, _, _ in strikes})
    curve = []
    for s_settle in candidates:
        payout = 0.0
        for k, cv, pv in strikes:
            payout += max(s_settle - k, 0) * cv + max(k - s_settle, 0) * pv
        curve.append({"settle": s_settle, "total_payout": payout})

    min_row = min(curve, key=lambda r: r["total_payout"])
    max_pain = min_row["settle"]
    dist_pct = (max_pain / price - 1) * 100

    # 赔付最敏感的两个邻点(引力区间)
    sorted_by_payout = sorted(curve, key=lambda r: r["total_payout"])[:3]

    result = {
        "symbol": symbol,
        "expiry": date,
        "underlying_price": price,
        "max_pain": max_pain,
        "distance_pct": round(dist_pct, 2),
        "total_payout_at_max_pain": round(min_row["total_payout"], 0),
        "top3_lowest_payout": [{"settle": r["settle"],
                                "payout": round(r["total_payout"], 0)}
                               for r in sorted_by_payout],
        "note": "成交量代理 OI(Longbridge chain 无按行权价 OI)。到期日当天参考意义最大。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} Max Pain(到期 {date},现价 {price})")
    print(f"  ⚠️ 基于成交量近似(非真实 OI)")
    print(f"  Max Pain 行权价: {max_pain}(距现价 {dist_pct:+.2f}%)")
    print(f"  引力区间(赔付最低的3个价位): "
          f"{' / '.join(str(r['settle']) for r in sorted_by_payout)}")
    # 展示赔付曲线采样
    show = [curve[i] for i in range(0, len(curve), max(1, len(curve) // 12))][:12]
    if curve[-1] not in show:
        show.append(curve[-1])
    print()
    print("总赔付曲线(采样):")
    print_display_table(
        [{"结算价": r["settle"], "总赔付": f"{r['total_payout']:,.0f}",
          "标记": "← Max Pain" if r["settle"] == max_pain else ""} for r in show],
        columns=["结算价", "总赔付", "标记"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Max Pain 最大痛点(成交量近似)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--date", default=None, help="到期日 YYYY-MM-DD(默认最近)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, date=args.date, output_json=args.output_json)
    except Exception as e:
        print_error("Max Pain", str(e))
        sys.exit(1)
