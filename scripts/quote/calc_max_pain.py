"""Max Pain(最大痛点)——期权到期时让买方整体损失最大的行权价。

理论: 做市商/卖方的对冲行为倾向于把价格"拉"向 Max Pain 价位
  (该价位上所有 Call+Put 的内在价值赔付总和最小)。
到期日效应: 越接近到期,价格向 Max Pain 收敛的引力越常被观察到。

权重口径(自动选择):
  ✅ 优先 **真实 OI**(calc-index 按合约逐个查询,存量持仓口径,与主流 Max Pain 一致)
  ⬇️ OI 拿不到时回退 **成交量代理**(chain 无按行权价 OI 的旧限制,输出已标注)

用法:
    python calc_max_pain.py MSFT.US --date 2026-09-18
    python calc_max_pain.py MSFT.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_chain_oi,
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

    # 1) 尝试真实 OI 口径
    weights: list[tuple[float, float, float]] = []  # (strike, call_w, put_w)
    mode = "volume"
    oi_data = get_chain_oi(symbol, date)
    if oi_data.get("oi_mode"):
        for s, v in sorted(oi_data["strikes"].items()):
            if v["call_oi"] or v["put_oi"]:
                weights.append((s, float(v["call_oi"]), float(v["put_oi"])))
        mode = "oi"
    if mode == "volume":
        chain = get_option_chain(symbol, date)
        if is_empty(chain):
            raise ValueError(f"{symbol} 在 {date} 无期权链")
        for r in chain:
            s = to_float(r.get("strike"))
            cv = to_float(r.get("call_vol"), 0) or 0
            pv = to_float(r.get("put_vol"), 0) or 0
            if s and (cv > 0 or pv > 0):
                weights.append((s, cv, pv))
    if not weights:
        raise ValueError("链上无有效权重数据(OI 与成交量均为空)")

    # 2) 对每个候选结算价 S,总赔付 = Σ max(S-K,0)·call_w + Σ max(K-S,0)·put_w
    candidates = sorted({s for s, _, _ in weights})
    curve = []
    for s_settle in candidates:
        payout = sum(max(s_settle - k, 0) * cw + max(k - s_settle, 0) * pw
                     for k, cw, pw in weights)
        curve.append({"settle": s_settle, "total_payout": payout})

    min_row = min(curve, key=lambda r: r["total_payout"])
    max_pain = min_row["settle"]
    dist_pct = (max_pain / price - 1) * 100
    sorted_by_payout = sorted(curve, key=lambda r: r["total_payout"])[:3]

    mode_note = ("真实 OI 加权(calc-index 按合约查询,存量持仓口径)"
                 if mode == "oi" else
                 "⚠️ 成交量近似加权(OI 不可用;Longbridge chain 无按行权价 OI,已自动回退)")

    result = {
        "symbol": symbol,
        "expiry": date,
        "underlying_price": price,
        "weight_mode": mode,
        "max_pain": max_pain,
        "distance_pct": round(dist_pct, 2),
        "total_payout_at_max_pain": round(min_row["total_payout"], 0),
        "top3_lowest_payout": [{"settle": r["settle"], "payout": round(r["total_payout"], 0)}
                               for r in sorted_by_payout],
        "strikes_used": len(weights),
        "note": f"{mode_note}。到期日当天参考意义最大。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} Max Pain(到期 {date},现价 {price})")
    print(f"  权重口径: {'✅ ' + '真实 OI' if mode == 'oi' else '⚠️ 成交量近似(回退)'}"
          f"({len(weights)} 档行权价)")
    print(f"  Max Pain 行权价: {max_pain}(距现价 {dist_pct:+.2f}%)")
    print(f"  引力区间(赔付最低的3个价位): "
          f"{' / '.join(str(r['settle']) for r in sorted_by_payout)}")
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
    parser = argparse.ArgumentParser(description="Max Pain 最大痛点(真实 OI 优先)")
    parser.add_argument("symbol", help="正股代码,如 MSFT.US")
    parser.add_argument("--date", default=None, help="到期日 YYYY-MM-DD(默认最近)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, date=args.date, output_json=args.output_json)
    except Exception as e:
        print_error("Max Pain", str(e))
        sys.exit(1)
