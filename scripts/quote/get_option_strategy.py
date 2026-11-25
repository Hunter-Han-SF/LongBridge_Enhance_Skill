"""生成标准期权策略组合腿(B 档·计算，支持买方/卖方/中性 11 种策略、目标 Delta 选腿与内联损益)。

对应 Futu: get_option_strategy(策略组合腿列表)

根据策略类型 + 标的现价，自动选择行权价并生成组合腿（支持 --otm-pct 或 --delta/--width）。
可直接通过 --with-pnl / --check-liquidity 一站式查看净权利金、盈亏平衡点、最大盈亏、胜率与流动性。

支持策略(11 种):
  STRADDLE          买 ATM Call + ATM Put(同一行权价)
  STRANGLE          买 OTM Call + OTM Put(不同行权价)
  BULL_CALL_SPREAD  买 ATM Call + 卖 OTM Call
  BEAR_PUT_SPREAD   买 ATM Put + 卖 OTM Put
  BUTTERFLY         买 ITM Call + 卖 2 ATM Call + 买 OTM Call
  COLLAR            买正股 + 买 OTM Put + 卖 OTM Call
  COVERED_CALL      买正股 + 卖 OTM Call
  CASH_SECURED_PUT  卖 OTM Put
  BULL_PUT_SPREAD   卖近价 OTM Put + 买远价保护 Put(牛市看跌信用价差)
  BEAR_CALL_SPREAD  卖近价 OTM Call + 买远价保护 Call(熊市看涨信用价差)
  IRON_CONDOR       卖 OTM Put + 买更低 Put + 卖 OTM Call + 买更高 Call(铁鹰式收租)

用法:
    python get_option_strategy.py AAPL.US 2026-12-18 STRADDLE
    python get_option_strategy.py AAPL.US 2026-12-18 BULL_CALL_SPREAD --otm-pct 0.05
    python get_option_strategy.py AAPL.US 2026-12-18 BULL_PUT_SPREAD --delta 0.20 --width 5 --with-pnl --check-liquidity
    python get_option_strategy.py AAPL.US 2026-12-18 IRON_CONDOR --delta 0.20 --width 5 --with-pnl
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.normpath(os.path.join(_HERE, "..")), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import (  # noqa: E402
    bs_greeks,
    build_lbr_option_symbol,
    days_to_years,
    get_option_chain,
    get_option_contract_metrics,
    get_underlying_price,
    get_underlying_price_info,
    parse_underlying,
    price_source_note,
    print_error,
    print_json,
    to_float,
    to_int,
)
from calc_option_pnl import _intrinsic, analyze_pnl  # noqa: E402
from get_iv_history import maybe_record_daily_iv  # noqa: E402

_SUPPORTED_STRATEGIES = (
    "STRADDLE",
    "STRANGLE",
    "BULL_CALL_SPREAD",
    "BEAR_PUT_SPREAD",
    "BUTTERFLY",
    "COLLAR",
    "COVERED_CALL",
    "CASH_SECURED_PUT",
    "BULL_PUT_SPREAD",
    "BEAR_CALL_SPREAD",
    "IRON_CONDOR",
)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _parse_pnl_bound(value) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    if isinstance(value, str) and "有限" in value:
        return to_float(value.split()[0])
    return None


def _compute_pop_bs_pct(
    legs: list[dict],
    pnl: dict,
    spot: float,
    T: float,
    rate: float,
    row_by_strike: dict[float, dict],
) -> float | None:
    """基于 PnL 盈亏平衡区间与链上 IV 计算 BS 风险中性到期胜率 POP (%)。"""
    if T <= 0 or not spot or spot <= 0:
        return None
    details = pnl.get("legs_detail") or []
    total_cost = to_float(pnl.get("total_cost"))
    if total_cost is None or len(details) != len(legs):
        return None

    short_ivs: list[float] = []
    all_ivs: list[float] = []
    payoff_legs: list[tuple[float, str, float]] = []
    for lg, det in zip(legs, details):
        ot = str(lg.get("type") or "").upper()
        action = str(lg.get("action") or "BUY").upper()
        qty = to_float(lg.get("quantity"), 1.0) or 1.0
        strike = to_float(lg.get("strike"))
        sign = 1.0 if action == "BUY" else -1.0
        if strike is None:
            return None
        if ot in ("STOCK", "SHARE", "UNDERLYING"):
            payoff_legs.append((strike, "STOCK", sign * qty * 100.0))
            continue
        cp = "C" if ot in ("CALL", "C") else "P"
        payoff_legs.append((strike, cp, sign * qty * 100.0))
        row = row_by_strike.get(strike) or {}
        iv = to_float(row.get("call_iv" if cp == "C" else "put_iv"))
        if iv and iv > 0:
            all_ivs.append(iv)
            if action == "SELL":
                short_ivs.append(iv)

    ref_ivs = short_ivs or all_ivs
    if not ref_ivs:
        return None
    sigma = sum(ref_ivs) / len(ref_ivs)
    if not math.isfinite(sigma) or sigma <= 0:
        return None

    def _payoff(settlement: float) -> float:
        return math.fsum(
            wt * (settlement if cp == "STOCK" else _intrinsic(settlement, k, cp))
            for k, cp, wt in payoff_legs
        ) - total_cost

    def _prob_above(bound: float | None) -> float:
        if bound is None:
            return 0.0
        if bound <= 0:
            return 1.0
        d2 = (math.log(spot / bound) + (rate - 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        return _norm_cdf(d2)

    roots = sorted({float(r) for r in (pnl.get("break_even_points") or []) if r is not None and r > 0})
    bounds: list[tuple[float, float | None]] = []
    prev = 0.0
    for r in roots:
        if r > prev + 1e-9:
            bounds.append((prev, r))
            prev = r
    bounds.append((prev, None))

    pop = 0.0
    for lo, hi in bounds:
        probe = (0.5 * (lo + hi)) if hi is not None else max(lo * 1.25, spot * 2.0, 1.0)
        if _payoff(probe) > 1e-6:
            pop += max(0.0, _prob_above(lo) - _prob_above(hi))
    return round(min(max(pop * 100.0, 0.0), 100.0), 1)


def _compute_bs_portfolio_greeks(
    legs: list[dict],
    spot: float,
    T: float,
    rate: float,
    row_by_strike: dict[float, dict],
) -> tuple[dict | None, dict[tuple[float, str], dict]]:
    """计算基于链上 IV 的组合 BS Greeks 与单腿 BS 指标。"""
    leg_bs: dict[tuple[float, str], dict] = {}
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    missing = False
    for lg in legs:
        ot = str(lg.get("type") or "").upper()
        action = str(lg.get("action") or "BUY").upper()
        qty = to_float(lg.get("quantity"), 1.0) or 1.0
        strike = to_float(lg.get("strike")) or 0.0
        sign = 1.0 if action == "BUY" else -1.0
        if ot in ("STOCK", "SHARE", "UNDERLYING"):
            totals["delta"] += 100.0 * sign * qty
            continue
        cp = "C" if ot in ("CALL", "C") else "P"
        row = row_by_strike.get(strike) or {}
        iv = to_float(row.get("call_iv" if cp == "C" else "put_iv"))
        if T <= 0 or not iv or iv <= 0 or spot <= 0 or strike <= 0:
            missing = True
            continue
        try:
            g = bs_greeks(spot, strike, T, rate, iv, cp)
        except ValueError:
            missing = True
            continue
        leg_bs[(strike, ot)] = {"iv": iv, **g}
        for k in totals:
            totals[k] += g[k] * sign * qty * 100.0

    if missing and not leg_bs:
        return None, leg_bs
    summary = {k: round(v, 4) for k, v in totals.items()}
    summary["basis"] = "BS(chain_iv)"
    summary["complete"] = not missing
    return summary, leg_bs


def build_strategy(
    underlying: str,
    expiry: str,
    strategy: str,
    otm_pct: float = 0.05,
    output_json: bool = False,
    *,
    target_delta: float | None = None,
    width: float | None = None,
    rate: float = 0.045,
    check_liquidity: bool = False,
    with_pnl: bool = False,
) -> dict:
    price = get_underlying_price(underlying)
    if not price or not math.isfinite(price) or price <= 0:
        raise ValueError(f"无法获取 {underlying} 现价")
    chain = get_option_chain(underlying, expiry)
    if not chain:
        raise ValueError(f"{underlying} 在 {expiry} 无期权链")

    if not math.isfinite(otm_pct) or not 0 < otm_pct < 1:
        raise ValueError("OTM 距离比例必须在 0 与 1 之间")
    if width is not None and (not math.isfinite(width) or width <= 0):
        raise ValueError("价差宽度 width 必须为有限正数")
    if target_delta is not None:
        if not math.isfinite(target_delta) or not 0.02 <= target_delta <= 0.49:
            raise ValueError("目标 Delta(|Δ|) 必须在 0.02 与 0.49 之间")

    row_by_strike: dict[float, dict] = {}
    for r in chain:
        if r.get("standard") is False:
            continue
        strike = to_float(r.get("strike"))
        if strike and strike > 0:
            row_by_strike[strike] = r
    strikes = sorted(row_by_strike)
    if not strikes:
        raise ValueError("无标准合约行权价")

    T = days_to_years(expiry)
    if target_delta is not None and T <= 0:
        raise ValueError(f"到期日 {expiry} 已过期或剩余时间为 0，无法按目标 Delta 选腿")

    atm = min(strikes, key=lambda k: abs(k - price))
    strat = strategy.upper()
    if strat not in _SUPPORTED_STRATEGIES:
        raise ValueError(f"不支持的策略 {strategy}。支持: {'/'.join(_SUPPORTED_STRATEGIES)}")

    call_floor = max(price, atm) if strat in ("BULL_CALL_SPREAD", "BUTTERFLY") else price
    put_ceiling = min(price, atm) if strat in ("BEAR_PUT_SPREAD", "BUTTERFLY") else price
    eff_width = width if width is not None else price * otm_pct

    def _pick_delta(side: str, cands: list[float], want_delta: float) -> float | None:
        iv_key = "call_iv" if side == "C" else "put_iv"
        scored = []
        for k in cands:
            iv = to_float((row_by_strike.get(k) or {}).get(iv_key))
            if not iv or iv <= 0:
                continue
            try:
                d = abs(bs_greeks(price, k, T, rate, iv, side)["delta"])
            except ValueError:
                continue
            scored.append((abs(d - want_delta), abs(k - price), k))
        return min(scored)[2] if scored else None

    call_cands = [k for k in strikes if k > call_floor]
    put_cands = [k for k in strikes if k < put_ceiling]

    if target_delta is not None:
        otm_call = _pick_delta("C", call_cands, target_delta)
        otm_put = _pick_delta("P", put_cands, target_delta)
        if strat in ("STRANGLE", "COLLAR", "COVERED_CALL", "BULL_CALL_SPREAD", "BEAR_CALL_SPREAD", "IRON_CONDOR") and otm_call is None:
            raise ValueError(f"{expiry} 链上 OTM Call 缺乏有效 IV，无法按目标 Delta {target_delta} 选腿")
        if strat in ("STRANGLE", "COLLAR", "CASH_SECURED_PUT", "BEAR_PUT_SPREAD", "BULL_PUT_SPREAD", "IRON_CONDOR") and otm_put is None:
            raise ValueError(f"{expiry} 链上 OTM Put 缺乏有效 IV，无法按目标 Delta {target_delta} 选腿")
    else:
        call_target = (call_floor + eff_width) if (width is not None and strat == "BULL_CALL_SPREAD") else price * (1 + otm_pct)
        put_target = (put_ceiling - eff_width) if (width is not None and strat == "BEAR_PUT_SPREAD") else price * (1 - otm_pct)
        otm_call = min(call_cands, key=lambda k: abs(k - call_target), default=None)
        otm_put = min(put_cands, key=lambda k: abs(k - put_target), default=None)

    itm_call = None
    long_call = None
    long_put = None
    if strat == "BUTTERFLY":
        widths = [atm - lower for lower in strikes if lower < atm
                  if any(math.isclose(upper - atm, atm - lower, abs_tol=1e-9)
                         for upper in strikes if upper > atm)]
        if not widths:
            raise ValueError("行权价不足以构成等宽蝶式")
        chosen_w = min(widths, key=lambda w: abs(w - eff_width))
        itm_call = atm - chosen_w
        otm_call = min(strikes, key=lambda k: abs(k - (atm + chosen_w)))

    if strat in ("BULL_PUT_SPREAD", "IRON_CONDOR") and otm_put is not None:
        long_put = min(
            (k for k in strikes if k < otm_put),
            key=lambda k: abs((otm_put - k) - eff_width),
            default=None,
        )
    if strat in ("BEAR_CALL_SPREAD", "IRON_CONDOR") and otm_call is not None:
        long_call = min(
            (k for k in strikes if k > otm_call),
            key=lambda k: abs((k - otm_call) - eff_width),
            default=None,
        )

    legs: list[dict] = []

    def leg(strike, otype, action, qty=1):
        if strike is None:
            raise ValueError(f"缺少符合 {strat} 方向约束的行权价")
        return {"underlying": underlying, "expiry": expiry, "strike": strike,
                "type": otype, "action": action, "quantity": qty}

    if strat == "STRADDLE":
        legs = [leg(atm, "CALL", "BUY"), leg(atm, "PUT", "BUY")]
    elif strat == "STRANGLE":
        legs = [leg(otm_call, "CALL", "BUY"), leg(otm_put, "PUT", "BUY")]
    elif strat == "BULL_CALL_SPREAD":
        legs = [leg(atm, "CALL", "BUY"), leg(otm_call, "CALL", "SELL")]
    elif strat == "BEAR_PUT_SPREAD":
        legs = [leg(atm, "PUT", "BUY"), leg(otm_put, "PUT", "SELL")]
    elif strat == "BUTTERFLY":
        legs = [leg(itm_call, "CALL", "BUY"), leg(atm, "CALL", "SELL", 2), leg(otm_call, "CALL", "BUY")]
    elif strat == "COLLAR":
        legs = [leg(price, "STOCK", "BUY"), leg(otm_put, "PUT", "BUY"), leg(otm_call, "CALL", "SELL")]
    elif strat == "COVERED_CALL":
        legs = [leg(price, "STOCK", "BUY"), leg(otm_call, "CALL", "SELL")]
    elif strat == "CASH_SECURED_PUT":
        legs = [leg(otm_put, "PUT", "SELL")]
    elif strat == "BULL_PUT_SPREAD":
        legs = [leg(otm_put, "PUT", "SELL"), leg(long_put, "PUT", "BUY")]
    elif strat == "BEAR_CALL_SPREAD":
        legs = [leg(otm_call, "CALL", "SELL"), leg(long_call, "CALL", "BUY")]
    elif strat == "IRON_CONDOR":
        legs = [
            leg(long_put, "PUT", "BUY"),
            leg(otm_put, "PUT", "SELL"),
            leg(otm_call, "CALL", "SELL"),
            leg(long_call, "CALL", "BUY"),
        ]

    bs_portfolio, leg_bs = _compute_bs_portfolio_greeks(legs, price, T, rate, row_by_strike)

    contract_metrics: dict[str, dict] = {}
    ticker, _ = parse_underlying(underlying)
    if check_liquidity:
        option_syms = []
        for lg in legs:
            if lg["type"] in ("CALL", "PUT"):
                option_syms.append(build_lbr_option_symbol(ticker, expiry, lg["strike"], lg["type"]))
        if option_syms:
            try:
                contract_metrics = get_option_contract_metrics(option_syms, fields="oi,iv,delta,gamma") or {}
            except Exception:
                contract_metrics = {}

    legs_meta: list[dict] = []
    low_oi_legs: list[str] = []
    zero_vol_legs: list[str] = []
    for lg in legs:
        ot = lg["type"]
        strike = lg["strike"]
        if ot == "STOCK":
            legs_meta.append({
                "strike": strike, "type": ot, "action": lg["action"], "quantity": lg["quantity"],
                "iv_pct": None, "bs_delta": 1.0 if lg["action"] == "BUY" else -1.0,
                "last": price, "volume": None, "open_interest": None, "liquidity_warning": None,
            })
            continue
        row = row_by_strike.get(strike) or {}
        is_call = ot == "CALL"
        last_px = to_float(row.get("call_last" if is_call else "put_last"))
        vol = to_int(row.get("call_vol" if is_call else "put_vol"))
        bs_entry = leg_bs.get((strike, ot)) or {}
        iv = bs_entry.get("iv") or to_float(row.get("call_iv" if is_call else "put_iv"))
        bs_d = bs_entry.get("delta")

        oi = None
        liq_warn = None
        if check_liquidity:
            csym = build_lbr_option_symbol(ticker, expiry, strike, ot)
            cm = contract_metrics.get(csym) or {}
            oi = to_int(cm.get("oi"))
            label = f"{lg['action']} {strike} {ot}"
            if oi is None:
                liq_warn = "未获取到OI"
                low_oi_legs.append(label)
            elif oi < 100:
                liq_warn = f"OI偏低({oi}<100)"
                low_oi_legs.append(label)
            if vol is None or vol == 0:
                zero_vol_legs.append(label)

        legs_meta.append({
            "strike": strike,
            "type": ot,
            "action": lg["action"],
            "quantity": lg["quantity"],
            "iv_pct": round(iv * 100, 2) if iv else None,
            "bs_delta": round(bs_d, 3) if bs_d is not None else None,
            "last": last_px,
            "volume": vol,
            "open_interest": oi,
            "liquidity_warning": liq_warn,
        })

    result = {
        "strategy": strat,
        "underlying": underlying,
        "expiry": expiry,
        "underlying_price": price,
        "underlying_price_source": get_underlying_price_info(underlying),
        "selection_mode": "delta" if target_delta is not None else "otm_pct",
        "target_delta": target_delta,
        "width": width,
        "atm_strike": atm,
        "otm_call_strike": otm_call,
        "otm_put_strike": otm_put,
        "otm_pct": otm_pct,
        "legs": legs,
        "legs_meta": legs_meta,
        "description": _describe(strat),
        "next_step": "把 legs 传给 calc_option_greeks.py 或 calc_option_pnl.py 分析",
    }
    if long_put is not None:
        result["long_put_strike"] = long_put
    if long_call is not None:
        result["long_call_strike"] = long_call
    if check_liquidity:
        result["liquidity"] = {
            "checked": True,
            "low_oi_legs": low_oi_legs,
            "zero_volume_legs": zero_vol_legs,
            "passed": len(low_oi_legs) == 0,
        }

    pnl_summary = None
    if with_pnl:
        pnl = analyze_pnl(legs, output_json=False, rate=rate, quiet=True,
                          underlying_price=price, chain=chain)
        max_profit_val = _parse_pnl_bound(pnl.get("max_profit"))
        max_loss_val = _parse_pnl_bound(pnl.get("max_loss"))
        ror = (
            round(max_profit_val / abs(max_loss_val) * 100.0, 1)
            if (max_profit_val is not None and max_loss_val is not None and max_loss_val < 0)
            else None
        )
        pop = _compute_pop_bs_pct(legs, pnl, price, T, rate, row_by_strike)
        total_cost = to_float(pnl.get("total_cost"), 0.0) or 0.0
        pnl_summary = {
            "total_cost": pnl.get("total_cost"),
            "net_credit": pnl.get("net_credit"),
            "net_cashflow": round(-total_cost, 2),
            "break_even_points": pnl.get("break_even_points"),
            "break_even_ranges": pnl.get("break_even_ranges"),
            "max_profit": pnl.get("max_profit"),
            "max_loss": pnl.get("max_loss"),
            "return_on_risk_pct": ror,
            "pop_bs_pct": pop,
            "estimated_legs": pnl.get("estimated_legs", 0),
            "legs_detail": pnl.get("legs_detail"),
        }
        result["pnl_summary"] = pnl_summary
        result["bs_portfolio_greeks"] = bs_portfolio

    maybe_record_daily_iv(underlying)

    if output_json:
        print_json(result)
        return result

    mode_str = (f"目标|Δ|≈{target_delta}" if target_delta is not None else f"OTM≈{otm_pct*100:.1f}%")
    if width is not None:
        mode_str += f", 翼宽={width}"
    print(f"策略: {strat}  标的 {underlying}(现价 {price}{price_source_note(underlying)})  到期 {expiry}  [{mode_str}]")
    print(f"  ATM={atm}  OTM Call={otm_call}  OTM Put={otm_put}")
    print(f"  {_describe(strat)}")
    print(f"  组合腿:")
    for lm in legs_meta:
        parts = [f"{lm['action']} {lm['quantity']}× {lm['strike']} {lm['type']}"]
        if lm.get("bs_delta") is not None and lm["type"] != "STOCK":
            parts.append(f"Δ={lm['bs_delta']:+.2f}")
        if lm.get("iv_pct") is not None:
            parts.append(f"IV={lm['iv_pct']}%")
        if lm.get("last") is not None and lm["type"] != "STOCK":
            parts.append(f"价={lm['last']}")
        if check_liquidity and lm["type"] != "STOCK":
            oi_s = str(lm["open_interest"]) if lm.get("open_interest") is not None else "N/A"
            vol_s = str(lm["volume"]) if lm.get("volume") is not None else "N/A"
            parts.append(f"OI={oi_s} Vol={vol_s}")
        if lm.get("liquidity_warning"):
            parts.append(f"⚠️{lm['liquidity_warning']}")
        print("    " + "  ".join(parts))

    if check_liquidity:
        liq = result["liquidity"]
        if liq["passed"]:
            print("  💧 流动性检查: ✅ 各期权腿 OI ≥ 100")
        else:
            print(f"  ⚠️ 流动性预警: {', '.join(liq['low_oi_legs'])}")
        if liq["zero_volume_legs"]:
            print(f"  ℹ️ 当日零成交腿: {', '.join(liq['zero_volume_legs'])}")

    if pnl_summary:
        cf = pnl_summary["net_cashflow"]
        cf_label = f"净收入权利金 +${cf:.2f}" if cf > 0 else f"净支出成本 ${abs(cf):.2f}"
        print(f"\n  ◆ 内联损益摘要:")
        print(f"    {cf_label}  |  盈亏平衡: {pnl_summary['break_even_points']}")
        print(f"    最大盈利: {pnl_summary['max_profit']}  |  最大亏损: {pnl_summary['max_loss']}")
        ror_s = f"{pnl_summary['return_on_risk_pct']}%" if pnl_summary["return_on_risk_pct"] is not None else "N/A"
        pop_s = f"{pnl_summary['pop_bs_pct']}%" if pnl_summary["pop_bs_pct"] is not None else "N/A"
        print(f"    风险回报率(ROR): {ror_s}  |  BS理论胜率(POP): {pop_s}")
        if pnl_summary["estimated_legs"]:
            print(f"    ⚠️ {pnl_summary['estimated_legs']} 腿当日无成交(last=0),成本已用 BS 理论价估算")
        if bs_portfolio:
            print(
                f"    BS 组合 Greeks: Δ={bs_portfolio['delta']}  Γ={bs_portfolio['gamma']}  "
                f"Θ={bs_portfolio['theta']}/日  Vega={bs_portfolio['vega']}/1%IV"
            )

    print(f"\n  把以下 JSON 传给 calc_option_pnl.py / calc_option_greeks.py:")
    print(json.dumps(legs, ensure_ascii=False))
    return result


def _describe(s: str) -> str:
    return {
        "STRADDLE": "买入同行权价 Call+Put,赌大波动(不计方向)",
        "STRANGLE": "买 OTM Call+Put,成本更低但需更大波动",
        "BULL_CALL_SPREAD": "买 ATM Call 卖 OTM Call,温和看多,成本降低",
        "BEAR_PUT_SPREAD": "买 ATM Put 卖 OTM Put,温和看空",
        "BUTTERFLY": "买 ITM+OTM Call 卖 2 ATM Call,赌价格稳定在 ATM",
        "COLLAR": "持股+买 Put+卖 Call,锁定下行牺牲上行",
        "COVERED_CALL": "持股+卖 OTM Call,收租降低成本",
        "CASH_SECURED_PUT": "卖 OTM Put,等跌到行权价接货",
        "BULL_PUT_SPREAD": "卖近价 OTM Put + 买远价保护 Put,温和看多/震荡收租,风险有限",
        "BEAR_CALL_SPREAD": "卖近价 OTM Call + 买远价保护 Call,温和看空/逢高收租,风险有限",
        "IRON_CONDOR": "同时卖出下方 Put 与上方 Call 信用价差,区间震荡赚时间价值衰减",
    }.get(s, s)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成标准期权策略组合腿(含卖方策略/Delta选腿/内联损益)")
    parser.add_argument("underlying", help="正股代码")
    parser.add_argument("expiry", help="到期日 YYYY-MM-DD")
    parser.add_argument("strategy", help="策略类型(见 --help 上方说明)")
    parser.add_argument("--otm-pct", type=float, default=0.05, help="OTM 距离比例(默认 0.05=5%%)")
    parser.add_argument("--delta", type=float, default=None, dest="target_delta",
                        help="按目标 |Delta| 选腿(如 0.20, 范围 0.02~0.49, 零额外API开销)")
    parser.add_argument("--width", type=float, default=None,
                        help="保护翼行权价宽度(美元, 如 5; 默认按 otm-pct 推算)")
    parser.add_argument("--rate", type=float, default=0.045, help="无风险利率(默认 0.045)")
    parser.add_argument("--check-liquidity", action="store_true",
                        help="批量校验各期权腿 OI 与当日成交量")
    parser.add_argument("--with-pnl", action="store_true",
                        help="内联计算净权利金、最大盈亏、盈亏平衡点、BS胜率(POP)与组合Greeks")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        build_strategy(
            args.underlying,
            args.expiry,
            args.strategy,
            otm_pct=args.otm_pct,
            output_json=args.output_json,
            target_delta=args.target_delta,
            width=args.width,
            rate=args.rate,
            check_liquidity=args.check_liquidity,
            with_pnl=args.with_pnl,
        )
    except Exception as e:
        print_error("策略生成", str(e))
        sys.exit(1)
