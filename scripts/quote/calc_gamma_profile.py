"""Gamma Profile —— 跨到期日聚合 GEX 剖面 + 插值 Gamma Flip + 细粒度支撑阻力。

对齐主流期权结构分析(如第三方面板的 "Gamma Flip ≈ 60 days")的计算方法:

  1. 聚合: 取未来 N 天(默认60)内所有到期日,对每个候选价位 S,把每条链
     各行权价的 GEX(S) 求和( Sticky-Strike 近似:每个行权价的 IV 固定用当前值,
     gamma 随假设价位 S 用 Black-Scholes 重算 )
  2. 翻转点: 在 GEX 剖面 GEX(S) 的符号变化处线性插值,取离现价最近的穿越点
     —— GEX>0 区做市商抑制波动,跌破 Flip 后转为放大波动(波动率机制切换)
  3. 支撑/阻力: 以 call OI / put OI 的核密度平滑曲线(高斯核,带宽=行权价间距)
     找局部极大值,抛物线插值细化到非整数价位(如 215.3),取现价下方/上方各 top3

数据成本: 每个到期日一次 get_chain_oi(约12次 calc-index 调用),
默认 8 个到期日 ≈ 100 次调用 ≈ 12 秒(限频 10/秒),结果带进程缓存。

用法:
    python calc_gamma_profile.py NVDA.US                     # 60天窗口
    python calc_gamma_profile.py NVDA.US --window 30        # 30天窗口
    python calc_gamma_profile.py NVDA.US --json
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    bs_greeks, days_to_years, get_chain_oi, get_option_expirations,
    get_underlying_price, print_display_table, print_error, print_json,
)

FLIP_T_FLOOR_DAYS = 0.5  # 避免当日到期链的 gamma 爆炸(除零)


def _collect_legs(symbol: str, window_days: int, range_pct: float) -> tuple[list[dict], float, list[str]]:
    """收集窗口内所有到期日的 (strike, iv, oi, T) 腿。返回 (legs, spot, expiries)。"""
    spot = get_underlying_price(symbol)
    if not spot:
        raise ValueError(f"无法获取 {symbol} 现价")
    expirations = get_option_expirations(symbol)
    if not expirations:
        raise ValueError(f"{symbol} 无可用到期日")

    legs: list[dict] = []
    used = []
    for exp in expirations:
        days = days_to_years(exp) * 365
        if days < 0 or days > window_days:
            continue
        oi = get_chain_oi(symbol, exp, near_atm_pct=range_pct * 1.15, max_strikes=60)
        if not oi.get("oi_mode"):
            continue
        T = max(days, FLIP_T_FLOOR_DAYS) / 365
        # 该到期日的可用 IV 中位数(个别行权价缺 IV 时的回退值)
        ivs = sorted(v for s in oi["strikes"].values()
                     for v in (s["call_iv"], s["put_iv"]) if v)
        med_iv = ivs[len(ivs) // 2] if ivs else None
        for s, v in oi["strikes"].items():
            if v["call_oi"]:
                legs.append({"strike": s, "iv": v["call_iv"] or med_iv,
                             "oi": float(v["call_oi"]), "T": T, "side": "C"})
            if v["put_oi"]:
                legs.append({"strike": s, "iv": v["put_iv"] or med_iv,
                             "oi": float(v["put_oi"]), "T": T, "side": "P"})
        used.append(exp)
    if not legs:
        raise ValueError("窗口内无 OI 数据(可能非美股或权限不足)")
    return legs, spot, used


def _gex_at(legs: list[dict], S: float, rate: float) -> float:
    """假设价位 S 下的总 GEX(sticky-strike IV + BS gamma)。call 正 / put 负。"""
    total = 0.0
    for leg in legs:
        iv = leg["iv"]
        if not iv or iv <= 0:
            continue
        g = bs_greeks(S, leg["strike"], leg["T"], rate, iv, leg["side"])["gamma"]
        sign = 1.0 if leg["side"] == "C" else -1.0
        total += sign * g * leg["oi"] * 100 * S * S * 0.01
    return total


def _find_flip(legs: list[dict], spot: float, rate: float,
               range_pct: float, steps: int = 160) -> tuple[float | None, list[dict]]:
    """在价位网格上算 GEX 剖面,返回 (插值翻转点, 剖面采样)。

    翻转点可能远离现价(深度价内持仓重的标的可达 -20% 以上),若在
    当前 range_pct 内无符号变化,自动扩域(×1.5、×2)重试,上限 0.40。
    """
    best: float | None = None
    profile: list[dict] = []
    for rng in (range_pct, range_pct * 1.5, 0.40):
        if rng > 0.40:
            break
        lo, hi = spot * (1 - rng), spot * (1 + rng)
        dx = (hi - lo) / steps
        xs = [lo + i * dx for i in range(steps + 1)]
        ys = [_gex_at(legs, x, rate) for x in xs]
        best = None
        for i in range(1, len(xs)):
            y0, y1 = ys[i - 1], ys[i]
            if (y0 <= 0 < y1) or (y0 >= 0 > y1):
                # 线性插值过零点
                x0, x1 = xs[i - 1], xs[i]
                cross = x0 + (0 - y0) * (x1 - x0) / (y1 - y0)
                # 取离现价最近的穿越点
                if best is None or abs(cross - spot) < abs(best - spot):
                    best = cross
        profile = [{"price": round(x, 2), "gex": y} for x, y in zip(xs, ys)]
        if best is not None:
            break
    return (round(best, 2) if best is not None else None), profile


def _sr_levels(legs: list[dict], spot: float, top_n: int = 3) -> dict:
    """OI 核密度局部极大值 → 插值细化的支撑/阻力价位。

    put OI 密度峰(现价下方)= 支撑;call OI 密度峰(现价上方)= 阻力。
    高斯核带宽取行权价间距中位数,峰值位置用抛物线插值细化到非整数价位。
    """
    def _density(side: str):
        ks = [l["strike"] for l in legs if l["side"] == side]
        if not ks:
            return [], []
        ks_sorted = sorted(ks)
        gaps = [b - a for a, b in zip(ks_sorted, ks_sorted[1:]) if b > a]
        h = (sorted(gaps)[len(gaps) // 2] if gaps else 1.0) * 1.0
        lo, hi = min(ks_sorted), max(ks_sorted)
        dx = h / 4
        xs, ys = [], []
        x = lo
        while x <= hi:
            y = sum(l["oi"] * math.exp(-((x - l["strike"]) ** 2) / (2 * h * h))
                    for l in legs if l["side"] == side)
            xs.append(x)
            ys.append(y)
            x += dx
        return xs, ys

    def _peaks(xs, ys, below: bool):
        peaks = []
        for i in range(1, len(xs) - 1):
            if ys[i] > ys[i - 1] and ys[i] >= ys[i + 1] and ys[i] > 0:
                if (below and xs[i] <= spot) or (not below and xs[i] >= spot):
                    # 抛物线插值细化峰值位置
                    den = ys[i - 1] - 2 * ys[i] + ys[i + 1]
                    delta = 0.5 * (ys[i - 1] - ys[i + 1]) / den if den else 0
                    delta = max(-0.5, min(0.5, delta))
                    peaks.append((xs[i] + delta * (xs[1] - xs[0]), ys[i]))
        peaks.sort(key=lambda p: p[1], reverse=True)
        out, seen = [], []
        for px, py in peaks:
            if all(abs(px - s) > 2.0 for s in seen):  # 去重:间距>2
                out.append({"price": round(px, 2), "density": round(py, 0)})
                seen.append(px)
            if len(out) >= top_n:
                break
        out.sort(key=lambda p: p["price"], reverse=below)
        return out

    xs_c, ys_c = _density("C")
    xs_p, ys_p = _density("P")
    return {"support": _peaks(xs_p, ys_p, below=True),
            "resistance": _peaks(xs_c, ys_c, below=False)}


def analyze(symbol: str, window_days: int = 60, range_pct: float = 0.20,
            rate: float = 0.045, output_json: bool = False) -> dict:
    legs, spot, used = _collect_legs(symbol, window_days, range_pct)
    total_oi = sum(l["oi"] for l in legs)

    flip, profile = _find_flip(legs, spot, rate, range_pct)
    gex_now = _gex_at(legs, spot, rate)
    sr = _sr_levels(legs, spot)

    if flip is None:
        regime = "区间内未检测到翻转(全区间同符号)"
    elif spot > flip:
        regime = (f"现价在翻转点上方 → 正 GEX 区(做市商抑制波动,偏稳);"
                  f"跌破 {flip} 转为负 GEX(放大波动,防守位)")
    else:
        regime = f"⚠️ 现价已在翻转点 {flip} 下方 → 负 GEX 区(做市商放大波动,易剧烈行情)"

    result = {
        "symbol": symbol,
        "underlying_price": spot,
        "window_days": window_days,
        "expiries_aggregated": used,
        "legs": len(legs),
        "total_oi": total_oi,
        "total_gex_at_spot": gex_now,
        "gamma_flip": flip,
        "regime": regime,
        "support_levels": sr["support"],
        "resistance_levels": sr["resistance"],
        "profile_sampled": [profile[i] for i in range(0, len(profile), len(profile) // 20 or 1)][:21],
        "note": ("Sticky-strike IV + BS gamma 重算剖面;S/R 为 OI 核密度峰的抛物线插值,非整数价位。"
                 "翻转点=剖面过零的线性插值,取离现价最近者。"),
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} Gamma Profile(聚合 {len(used)} 个到期日 / {window_days} 天窗口,"
          f"{len(legs):,} 条腿,总 OI {total_oi:,.0f})")
    print(f"  现价: {spot}   总 GEX@现价: {gex_now:,.0f}")
    print(f"  Gamma Flip(插值): {flip}")
    print(f"  机制: {regime}")
    print()
    print("支撑位(put OI 密度峰,插值):")
    print_display_table(
        [{"价位": f"{p['price']:.2f}", "距现价": f"{(p['price']/spot-1)*100:+.1f}%",
          "OI密度": f"{p['density']:,.0f}"} for p in sr["support"]] or [{"价位": "-"}],
        columns=["价位", "距现价", "OI密度"])
    print("阻力位(call OI 密度峰,插值):")
    print_display_table(
        [{"价位": f"{p['price']:.2f}", "距现价": f"{(p['price']/spot-1)*100:+.1f}%",
          "OI密度": f"{p['density']:,.0f}"} for p in sr["resistance"]] or [{"价位": "-"}],
        columns=["价位", "距现价", "OI密度"])
    print()
    print("GEX 剖面(采样,price → GEX):")
    step = max(1, len(profile) // 10)
    print_display_table(
        [{"价位": p["price"], "GEX": f"{p['gex']:,.0f}",
          "符号": "正(稳)" if p["gex"] > 0 else "负(波动)"} for p in profile[::step]][:12],
        columns=["价位", "GEX", "符号"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gamma Profile:聚合GEX剖面+插值Flip+细粒度S/R")
    parser.add_argument("symbol", help="正股代码,如 NVDA.US")
    parser.add_argument("--window", type=int, default=60, help="聚合窗口天数(默认 60)")
    parser.add_argument("--range", type=float, default=0.20, dest="range_pct",
                        help="剖面价位范围 ±比例(默认 0.20)")
    parser.add_argument("--rate", type=float, default=0.045, help="无风险利率")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, window_days=args.window, range_pct=args.range_pct,
                rate=args.rate, output_json=args.output_json)
    except Exception as e:
        print_error("Gamma Profile", str(e))
        sys.exit(1)
