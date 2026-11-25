"""买卖决策仪表盘(多维度聚合 → 多空对照 + 综合信号)。

旗舰脚本: 把全部模块的判断压缩成一页纸,回答"当下偏买还是偏卖"。
聚合六维(每维失败不致命,跳过并标注):
  ① 技术面(30%): calc_technical_score 综合分
  ② 估值面(15%): 估值历史百分位(便宜=高分)
  ③ 资金面(20%): 主力大单净流入方向 + 沽空压力
  ④ 期权定位(10%): P/C 比率 + IV 贵贱(仅美股)
  ⑤ 分析师(15%): 评级共识 + 目标价空间
  ⑥ 事件风险: 临近财报最多削弱 7 分看多信号，独立于方向评分

输出:
  - 方向维度得分和覆盖权重，财报风险单列
  - 多头因素 vs 空头因素 对照清单
  - 综合信号: 看多/偏多/中性/偏空/看空

⚠️ 本工具是数据聚合参考,非投资建议;权重为设计选择。

用法:
    python analyze_buy_sell.py AAPL.US
    python analyze_buy_sell.py 0700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.normpath(os.path.join(_HERE, "..")), _HERE,
           os.path.normpath(os.path.join(_HERE, "..", "technical")),
           os.path.normpath(os.path.join(_HERE, "..", "fundamental")),
           os.path.normpath(os.path.join(_HERE, "..", "quote")),
           os.path.normpath(os.path.join(_HERE, "..", "market")),
           os.path.normpath(os.path.join(_HERE, "..", "calendar"))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common
from common import (  # noqa: E402
    calc_hv, days_to_years, get_atm_iv, get_capital_flow_snapshot, get_finance_calendar,
    get_kline_adjusted, get_option_chain, get_option_expirations, get_option_volume_realtime,
    get_short_trades, get_underlying_price, get_underlying_price_info, nearest_tenor_expiry,
    price_source_note, print_error, print_json, rank_tenor_expiries, regular_session_price,
    to_float,
)
from calc_technical_score import score as tech_score  # noqa: E402
from get_valuation_percentile import analyze as val_analyze  # noqa: E402
from get_analyst_consensus import analyze as analyst_analyze  # noqa: E402
from get_market_regime import assess_market_regime  # noqa: E402

WEIGHTS = {"技术面": 30, "估值面": 15, "资金面": 20, "期权定位": 10, "分析师": 15}
MIN_COVERAGE_WEIGHT = 60
EVENT_PENALTY = 7
MAX_EVENT_PENALTY = 15


def _dim_technical(symbol: str, bulls: list, bears: list) -> tuple[float | None, str]:
    try:
        r = tech_score(symbol, quiet=True)
        for s in (r.get("signals") or [])[:4]:
            if s.startswith("🟢"):
                bulls.append(f"技术: {s[2:]}")
            elif s.startswith("🔴"):
                bears.append(f"技术: {s[2:]}")
        return r["technical_score"], r["label"]
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def _dim_valuation(symbol: str, bulls: list, bears: list) -> tuple[float | None, str]:
    try:
        r = val_analyze(symbol, quiet=True)
        main = r.get("main") or {}
        p = main.get("percentile")
        if p is None:
            return None, "无数据"
        # 便宜(低分位)= 高分
        score = 100 - p
        if p < 30:
            bulls.append(f"估值: {main.get('metric')} 处历史 {p:.0f}% 低分位(便宜)")
        elif p > 70:
            bears.append(f"估值: {main.get('metric')} 处历史 {p:.0f}% 高分位(偏贵)")
        return score, f"{main.get('metric')} {main.get('current')}(历史{p:.0f}%分位)"
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def _dim_capital(symbol: str, bulls: list, bears: list) -> tuple[float | None, str]:
    try:
        cap = get_capital_flow_snapshot(symbol)
        net_large = to_float((cap.get("net") or {}).get("large"))
        li = to_float((cap.get("capital_in") or {}).get("large"))
        lo = to_float((cap.get("capital_out") or {}).get("large"))
        gross = li + lo if li is not None and lo is not None and li >= 0 and lo >= 0 else None
        s = None
        detail = []
        if net_large is not None and gross and abs(net_large) <= gross:
            ratio = net_large / gross
            s = 50 + 50 * max(-1, min(1, ratio / 0.10))
            if cap.get("unit_verified"):
                amount = f"{net_large / 1e4:+.0f}万(当地货币)"
            elif abs(net_large) >= 100:
                amount = f"{net_large:+,.0f}(源数值，货币单位未核实)"
            else:
                amount = f"{net_large:+g}(源数值，货币单位未核实)"
            detail.append(f"大单净额 {amount}")
            if ratio:
                (bulls if ratio > 0 else bears).append(
                    f"资金: 大单净额 {amount}，占大单总流量 {ratio:+.0%}"
                )
        # 沽空: 港股卖空成交占比按阈值计分。美股是 FINRA 空头成交量占比,含做市商对冲,
        # 各股常态水平不同(2026-11 实测 17%~58%),绝对值不反映看空情绪 —— 只展示、不计分
        try:
            st = get_short_trades(symbol, count=10)
            given = st.get("data") or []
            dated = [r for r in given if to_float(r.get("timestamp"))]
            rows = sorted(dated, key=lambda r: to_float(r["timestamp"])) if dated else list(given)
            latest = to_float(rows[-1].get("rate")) if rows else None
            if latest is not None and 0 <= latest <= 1:
                is_us = st.get("market") == "US" or (
                    st.get("market") is None and symbol.upper().endswith(".US"))
                if is_us:
                    earlier = [v for v in (to_float(r.get("rate")) for r in rows[:-1]) if v is not None]
                    text = f"空头成交占比 {latest:.0%}(FINRA,含做市对冲,不计分"
                    if len(earlier) >= 3:
                        text += f",此前均值 {sum(earlier) / len(earlier):.0%}"
                    detail.append(text + ")")
                else:
                    s = 50 if s is None else s
                    detail.append(f"沽空率 {latest:.0%}")
                    if latest >= 0.3:
                        s -= 10
                        bears.append(f"沽空: 最新沽空成交占比 {latest:.0%}")
                    elif latest <= 0.1:
                        s += 5
        except Exception:
            pass
        if s is not None:
            return max(min(s, 100), 0), ", ".join(detail)
        # 没有可计分的资金数据时仍带出已取得的明细(如美股空头成交占比,只展示不计分)
        return None, ", ".join(detail) or "无数据"
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def _dim_options(symbol: str, bulls: list, bears: list, price: float | None = None) -> tuple[float | None, str]:
    if not symbol.upper().endswith(".US"):
        return None, "非美股，期权维度不适用"
    try:
        s = 50.0
        parts = []
        pc = get_option_volume_realtime(symbol).get("pc_ratio")
        if pc is not None:
            parts.append(f"P/C {pc:.2f}")
            if pc > 1.0:
                s -= 15
                bears.append(f"期权: P/C 比率 {pc:.2f}(看跌对冲偏重)")
            elif pc < 0.7:
                s += 10
                bulls.append(f"期权: P/C 比率 {pc:.2f}(偏多)")
        # IV vs HV —— 期限必须对齐,且若目标期限的新挂牌周链尚无 IV 则依次回退到有有效 IV 的最近期限链。
        exps = get_option_expirations(symbol)
        if exps:
            spot = get_underlying_price(symbol) if price is None else price
            atm_ref = (regular_session_price(symbol, spot) or spot) if spot else None
            chosen_exp = iv = None
            if atm_ref:
                for cand in rank_tenor_expiries(exps, 30 * 365 / 252):
                    chain = get_option_chain(symbol, cand)
                    cand_iv = get_atm_iv(chain, atm_ref)
                    if cand_iv and cand_iv > 0:
                        chosen_exp, iv = cand, cand_iv
                        break
            if iv and chosen_exp:
                try:
                    hv_win = max(2, round(days_to_years(chosen_exp) * 252))
                except ValueError:
                    hv_win = 30
                klines = get_kline_adjusted(symbol, count=hv_win + 1)
                closes = [k["close"] for k in klines if k.get("close") is not None]
                hv = calc_hv(closes)
                if hv:
                    parts.append(f"IV/HV {iv/hv:.2f}")
                    if iv / hv > 1.3:
                        s += 5  # IV 贵 → 卖方占优,对持有正股者偏中性偏正(收租机会)
                        bulls.append(f"期权: IV 偏贵(IV/HV {iv/hv:.2f},卖权收租机会)")
                    elif iv / hv < 0.8:
                        s -= 5
        return (max(min(s, 100), 0), ", ".join(parts)) if parts else (None, "无数据")
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def _dim_analyst(symbol: str, bulls: list, bears: list) -> tuple[float | None, str]:
    try:
        r = analyst_analyze(symbol, quiet=True)
        rat = r.get("rating") or {}
        total = to_float(rat.get("total"), 0) or 0
        if total <= 0:
            return None, "无评级覆盖"
        bull = ((to_float(rat.get("buy"), 0) or 0) + (to_float(rat.get("over"), 0) or 0))
        bear = ((to_float(rat.get("sell"), 0) or 0) + (to_float(rat.get("under"), 0) or 0))
        s = 50 + (bull - bear) / total * 50
        raw_label = str(rat.get("label") or "")
        clean_label = raw_label.lstrip("🟢🔴⚪ ").strip() or raw_label
        if bull / total >= 0.6:
            bulls.append(f"分析师: {clean_label}({int(round(bull))}/{int(round(total))} 家看多)")
        if bear / total >= 0.3:
            bears.append(f"分析师: {int(round(bear))}/{int(round(total))} 家看空")
        t = r.get("target_price") or {}
        up = t.get("upside_to_mid_pct")
        if up is not None:
            if up > 15:
                s = min(s + 10, 100)
                bulls.append(f"目标价: 距共识目标还有 {up:+.1f}% 空间")
            elif up < -10:
                s = max(s - 10, 0)
                bears.append(f"目标价: 现价已高于共识目标 {abs(up):.1f}%")
        return max(min(s, 100), 0), f"{raw_label},共识目标空间 {up:+.1f}%" if up is not None else raw_label
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def _dim_event(
    symbol: str,
    bulls: list,
    bears: list,
    *,
    include_regime: bool = False,
    regime_out: dict | None = None,
) -> tuple[float | None, str]:
    market = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else "US"
    earn_pen: float | None = None
    earn_note: str = ""
    earn_err: str | None = None
    try:
        buckets = get_finance_calendar(category="report", market=market, symbol=symbol, count=20)
        today = common.market_date(market)
        # 取「最近一次」未来财报(日历返回乱序时不能只拿第一个命中的)
        best_days = None
        for b in buckets:
            for info in b.get("infos", []):
                d = str(info.get("date", "")).replace(".", "-")[:10]
                try:
                    days = (datetime.strptime(d, "%Y-%m-%d").date() - today).days
                except ValueError:
                    continue
                if days >= 0 and (best_days is None or days < best_days):
                    best_days = days
        if best_days is not None:
            if best_days <= 7:
                bears.append(f"事件: {best_days} 天后发财报(波动风险)")
                earn_pen, earn_note = float(EVENT_PENALTY), f"{best_days} 天后财报"
            else:
                earn_pen, earn_note = 0.0, f"下次财报还有 {best_days} 天"
        else:
            earn_note = "日历中无可核实的下次财报"
    except Exception as e:
        earn_err = f"数据失败({str(e)[:30]})"
        earn_note = earn_err

    if not include_regime:
        if earn_err is not None:
            return None, earn_err
        return earn_pen, earn_note

    reg_pen = 0.0
    reg_note = ""
    try:
        reg = assess_market_regime(market)
        if isinstance(reg, dict) and reg.get("regime") and reg.get("regime") != "unknown":
            if regime_out is not None:
                regime_out.update(reg)
            reg_pen = to_float(reg.get("max_bull_penalty"), 0.0) or 0.0
            summary = reg.get("summary") or ""
            label = reg.get("label") or reg.get("regime")
            if reg["regime"] in ("risk_off", "caution"):
                bears.append(f"大盘/宏观: {label}" + (f" — {summary}" if summary else ""))
            elif reg["regime"] == "risk_on":
                bulls.append(f"大盘环境: {label}" + (f"({summary})" if summary else ""))
            reg_note = f"{label}" + (f"({summary})" if summary else "")
    except Exception:
        pass

    if earn_pen is None and not reg_note:
        return None, earn_note
    total_pen = min(float(MAX_EVENT_PENALTY), (earn_pen or 0.0) + reg_pen)
    note = f"{earn_note}; 大盘 {reg_note}" if reg_note else earn_note
    return total_pen, note


def analyze(symbol: str, output_json: bool = False, include_regime: bool = True) -> dict:
    price = get_underlying_price(symbol)
    bulls: list[str] = []
    bears: list[str] = []

    dims = {
        "技术面": _dim_technical(symbol, bulls, bears),
        "估值面": _dim_valuation(symbol, bulls, bears),
        "资金面": _dim_capital(symbol, bulls, bears),
        "期权定位": _dim_options(symbol, bulls, bears, price=price),
        "分析师": _dim_analyst(symbol, bulls, bears),
    }

    total_w = 0.0
    acc = 0.0
    dim_out = {}
    for name, (score_v, note) in dims.items():
        if score_v is None:
            dim_out[name] = {"score": None, "weight": WEIGHTS[name], "detail": note}
            continue
        acc += score_v * WEIGHTS[name]
        total_w += WEIGHTS[name]
        dim_out[name] = {"score": round(score_v, 1), "weight": WEIGHTS[name], "detail": note}
    regime_box: dict = {}
    event_penalty, event_note = _dim_event(
        symbol, bulls, bears, include_regime=include_regime, regime_out=regime_box
    )
    coverage_ok = total_w >= MIN_COVERAGE_WEIGHT and dims["技术面"][0] is not None
    directional_score = acc / total_w if coverage_ok else None
    # 风险只能削弱看多信号，财报日期与大盘逆风不将原本看空得分进一步压低或伪造多头。
    composite = (round(directional_score - min(event_penalty or 0, max(directional_score - 50, 0)), 1)
                 if directional_score is not None else None)
    applicable_weight = sum(WEIGHTS.values()) - (0 if symbol.upper().endswith(".US") else WEIGHTS["期权定位"])

    if composite is None:
        signal = "数据不足"
    elif composite >= 70:
        signal = "🟢🟢 看多"
    elif composite >= 55:
        signal = "🟢 偏多"
    elif composite > 45:
        signal = "⚪ 中性"
    elif composite > 30:
        signal = "🔴 偏空"
    else:
        signal = "🔴🔴 看空"

    result = {
        "symbol": symbol,
        "price": price,
        "underlying_price_source": get_underlying_price_info(symbol),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dimensions": dim_out,
        "composite_score": composite,
        "directional_score": round(directional_score, 1) if directional_score is not None else None,
        "coverage_weight": total_w,
        "applicable_weight": applicable_weight,
        "minimum_coverage_weight": MIN_COVERAGE_WEIGHT,
        "required_dimensions": ["技术面"],
        "event_risk": {"max_penalty": event_penalty, "detail": event_note},
        "market_regime": regime_box or None,
        "signal": signal,
        "bull_factors": bulls,
        "bear_factors": bears,
        "disclaimer": "数据聚合参考,非投资建议。权重为设计选择,请结合自身判断。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{'='*56}")
    print(f"  {symbol} 买卖决策仪表盘  现价 {price}{price_source_note(symbol)}  {result['generated_at']}")
    print(f"{'='*56}")
    print(f"\n  综合信号: {signal}  (综合分 {composite}/100)\n")
    print(f"方向评分覆盖权重 {total_w:g}/{applicable_weight}（至少 {MIN_COVERAGE_WEIGHT}，须含技术面）")
    print("方向评分:")
    for name, d in dim_out.items():
        sc = f"{d['score']:.0f}/100" if d["score"] is not None else "N/A"
        print(f"  [{name}](权重{d['weight']}) {sc} — {d['detail']}")
    print(f"  事件风险：{event_note}")
    if regime_box:
        print(f"  大盘环境：{regime_box.get('label', '')} — {regime_box.get('summary', '')}")
    print(f"\n  多头因素({len(bulls)}):")
    for b in bulls or ["(无)"]:
        print(f"    🟢 {b}")
    print(f"  空头因素({len(bears)}):")
    for b in bears or ["(无)"]:
        print(f"    🔴 {b}")
    print(f"\n  ⚠️ {result['disclaimer']}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="买卖决策仪表盘(六维聚合)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 0700.HK")
    parser.add_argument("--no-regime", action="store_true", dest="no_regime",
                        help="跳过大盘环境与 3 星宏观催化评估(加速)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, output_json=args.output_json, include_regime=not args.no_regime)
    except Exception as e:
        print_error("买卖仪表盘", str(e))
        sys.exit(1)
