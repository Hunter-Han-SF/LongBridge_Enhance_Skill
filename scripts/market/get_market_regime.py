"""大盘环境状态评估(Market Regime) + 重磅宏观催化预警。

数据源(均来自 Longbridge CLI 只读接口):
  - 美股(.US): `.VIX.US`(恐慌指数)、`SPY.US` & `QQQ.US`(含盘前/盘后/夜盘跳空 +
    前复权日K MA20/50/200) + `finance-calendar macrodata --star 3`(FOMC/CPI/PCE/非农/GDP)
  - 港/A/新股: 对应基准指数 ETF(`2800.HK`/`510300.SH`)、市场温度(`market-temp`) + 3 星宏观

输出四档 Regime:
  - risk_on : 顺风偏多(主流宽基站稳 MA20/50, VIX < 20, 无 24h 内 Tier-1 核心宏观)
  - neutral : 震荡中性
  - caution : 逆风/宏观前夕(跌破 MA20, 或 VIX 22+, 或 24h 内有 FOMC/CPI/PCE/非农等)
  - risk_off: 系统性避险(VIX ≥ 28 或单日飙升 ≥15% 破 24, 或宽基集体跌破 MA50 伴大跌/暴跌跳空)

用法:
    python get_market_regime.py
    python get_market_regime.py --market HK
    python get_market_regime.py --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (
    os.path.normpath(os.path.join(_HERE, "..")),
    os.path.normpath(os.path.join(_HERE, "..", "technical")),
    os.path.normpath(os.path.join(_HERE, "..", "calendar")),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import (  # noqa: E402
    get_batch_quotes,
    get_finance_calendar,
    get_kline_adjusted,
    get_market_temp,
    latest_underlying_price,
    market_now,
    market_temp_label,
    print_display_table,
    print_error,
    print_json,
    to_float,
)
from get_macro_calendar import _flatten_macro  # noqa: E402
from indicators import sma_series  # noqa: E402

_BENCHMARKS = {
    "US": ["SPY.US", "QQQ.US"],
    "HK": ["2800.HK"],
    "CN": ["510300.SH"],
    "SH": ["510300.SH"],
    "SZ": ["510300.SH"],
}


def _analyze_benchmark(symbol: str, quote: dict | None, current: datetime) -> dict:
    bars = get_kline_adjusted(symbol, count=220)
    closes = [
        px for px in (to_float((b or {}).get("close")) for b in (bars or []))
        if px is not None and px > 0
    ]
    ma20 = round(sma_series(closes, 20)[-1], 2) if len(closes) >= 20 and sma_series(closes, 20)[-1] else None
    ma50 = round(sma_series(closes, 50)[-1], 2) if len(closes) >= 50 and sma_series(closes, 50)[-1] else None
    ma200 = round(sma_series(closes, 200)[-1], 2) if len(closes) >= 200 and sma_series(closes, 200)[-1] else None

    latest_px, px_info = latest_underlying_price(quote, current)
    if latest_px is None and closes:
        latest_px = closes[-1]
        px_info = {"price": latest_px, "source": "kline_close", "source_label": "日K收盘",
                   "regular_price": latest_px}

    reg_px = to_float((quote or {}).get("regular_price")) or (closes[-1] if closes else None)
    source = (px_info or {}).get("source") or "regular"
    ext_gap_pct = (
        round((latest_px - reg_px) / reg_px * 100, 2)
        if source not in ("regular", "kline_close") and latest_px and reg_px and reg_px > 0
        else None
    )
    q_chg = to_float((quote or {}).get("change_percentage"))
    day_chg_pct = ext_gap_pct if ext_gap_pct is not None else q_chg

    return {
        "symbol": symbol,
        "price": round(latest_px, 2) if latest_px is not None else None,
        "regular_price": round(reg_px, 2) if reg_px is not None else None,
        "price_source": source,
        "source_label": (px_info or {}).get("source_label") or "常规时段",
        "change_pct": round(day_chg_pct, 2) if day_chg_pct is not None else None,
        "ext_gap_pct": ext_gap_pct,
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "above_ma20": (latest_px > ma20) if (latest_px is not None and ma20) else None,
        "above_ma50": (latest_px > ma50) if (latest_px is not None and ma50) else None,
        "above_ma200": (latest_px > ma200) if (latest_px is not None and ma200) else None,
    }


def _collect_macro_catalysts(cal_market: str, current: datetime) -> dict:
    start_d = (current.date() - timedelta(days=1)).isoformat()
    end_d = (current.date() + timedelta(days=3)).isoformat()
    try:
        buckets = get_finance_calendar(
            category="macrodata",
            market=cal_market,
            start=start_d,
            end=end_d,
            count=100,
            star=3,
        )
    except Exception:
        return {"tier1_24h": [], "tier1_48h": [], "tier1_recent": [], "star3_upcoming": []}

    events = _flatten_macro(buckets)
    now_ts = current.timestamp()
    tier1_24h, tier1_48h, tier1_recent, star3_upcoming = [], [], [], []
    seen_names: set[tuple[str, str]] = set()

    for ev in events:
        if ev.get("star") not in (3, None):
            continue
        if ev.get("star") is None:
            continue
        ts = to_float(ev.get("release_ts"))
        hours = None
        if ts is not None and ts > 1e8:
            hours = round((ts - now_ts) / 3600.0, 1)
        else:
            ed = str(ev.get("event_date") or "")[:10]
            try:
                days = (date.fromisoformat(ed) - current.date()).days
                hours = float(days * 24)
            except ValueError:
                hours = None
        if hours is None:
            continue

        item = {
            "name": ev.get("name", ""),
            "date": ev.get("date", ""),
            "event_date": ev.get("event_date", ""),
            "time": ev.get("time", ""),
            "hours_until": hours,
            "previous": ev.get("previous", ""),
            "estimate": ev.get("estimate", ""),
            "actual": ev.get("actual", ""),
            "released": bool(ev.get("released")),
            "star": ev.get("star"),
            "tier": ev.get("tier"),
        }
        dedup_key = (item["event_date"], item["name"])
        if dedup_key in seen_names:
            continue
        seen_names.add(dedup_key)

        if not item["released"] and -0.5 <= hours <= 72:
            star3_upcoming.append(item)
        if item["tier"] == "tier1":
            if item["released"] and -4.0 <= hours <= 0.5:
                tier1_recent.append(item)
            elif not item["released"] and -0.5 <= hours <= 24.0:
                tier1_24h.append(item)
            elif not item["released"] and 24.0 < hours <= 48.0:
                tier1_48h.append(item)

    star3_upcoming.sort(key=lambda x: x["hours_until"])
    tier1_24h.sort(key=lambda x: x["hours_until"])
    tier1_48h.sort(key=lambda x: x["hours_until"])
    tier1_recent.sort(key=lambda x: x["hours_until"], reverse=True)
    return {
        "tier1_24h": tier1_24h,
        "tier1_48h": tier1_48h,
        "tier1_recent": tier1_recent,
        "star3_upcoming": star3_upcoming,
    }


def _short_bm_text(b: dict) -> str:
    sym = str(b.get("symbol") or "").split(".")[0]
    px = b.get("price")
    if px is None:
        return f"{sym} N/A"
    chg = b.get("change_pct")
    src = b.get("source_label") or ""
    if b.get("price_source") in ("pre_market", "post_market", "overnight") and chg is not None:
        chg_part = f"{src} {chg:+.1f}%"
    elif chg is not None:
        chg_part = f"{chg:+.1f}%"
    else:
        chg_part = ""
    ma_part = ""
    if b.get("above_ma50") is False:
        ma_part = "跌破MA50"
    elif b.get("above_ma20") is False:
        ma_part = "跌破MA20"
    elif b.get("above_ma20") is True:
        ma_part = "站上MA20"
    extra = ",".join(x for x in (chg_part, ma_part) if x)
    return f"{sym} {px:g}" + (f"({extra})" if extra else "")


def assess_market_regime(market: str = "US", now: datetime | None = None) -> dict:
    """评估当前市场大盘环境与 24-48h 核心宏观事件风险。"""
    mkt = (market or "US").upper()
    cal_mkt = "CN" if mkt in ("SH", "SZ") else mkt
    current = now if now is not None else market_now(mkt)
    if current.tzinfo is None:
        current = market_now(mkt, now=current)

    bm_symbols = _BENCHMARKS.get(mkt, ["SPY.US", "QQQ.US"])
    query_syms = ([".VIX.US"] + bm_symbols) if mkt == "US" else list(bm_symbols)
    quotes = get_batch_quotes(query_syms) if query_syms else {}

    benchmarks = {}
    for sym in bm_symbols:
        try:
            benchmarks[sym] = _analyze_benchmark(sym, quotes.get(sym.upper()), current)
        except Exception:
            benchmarks[sym] = {
                "symbol": sym, "price": None, "regular_price": None,
                "price_source": "unavailable", "source_label": "未知",
                "change_pct": None, "ext_gap_pct": None,
                "ma20": None, "ma50": None, "ma200": None,
                "above_ma20": None, "above_ma50": None, "above_ma200": None,
            }

    vix = None
    vix_state = "unknown"
    if mkt == "US":
        vq = quotes.get(".VIX.US") or {}
        vix_level = to_float(vq.get("regular_price"))
        vix_chg = to_float(vq.get("change_percentage"))
        if vix_level is not None and vix_level > 0:
            if vix_level >= 28 or (vix_level >= 24 and (vix_chg or 0) >= 15):
                vix_state = "panic"
            elif vix_level >= 22 or (vix_chg or 0) >= 10:
                vix_state = "elevated"
            else:
                vix_state = "calm"
        vix = {"symbol": ".VIX.US", "level": vix_level, "change_pct": vix_chg, "state": vix_state}

    mkt_temp = None
    if mkt != "US":
        try:
            t = get_market_temp(cal_mkt)
            if isinstance(t, dict) and to_float(t.get("temperature")) is not None:
                mkt_temp = t
        except Exception:
            mkt_temp = None

    macro = _collect_macro_catalysts(cal_mkt, current)
    tier1_24h = macro["tier1_24h"]
    tier1_48h = macro["tier1_48h"]
    tier1_recent = macro["tier1_recent"]
    star3_upcoming = macro["star3_upcoming"]

    bms = [b for b in benchmarks.values() if b.get("price") is not None]
    warnings: list[str] = []

    if mkt == "US":
        if not bms and (not vix or vix.get("level") is None):
            regime, label, max_penalty = "unknown", "⚪ 未知(无大盘行情)", 0
        else:
            all_below_ma50 = bool(bms) and all(b.get("above_ma50") is False for b in bms)
            any_below_ma20 = any(b.get("above_ma20") is False for b in bms)
            all_below_ma20 = bool(bms) and all(b.get("above_ma20") is False for b in bms)
            min_chg = min((b["change_pct"] for b in bms if b.get("change_pct") is not None), default=None)

            if vix_state == "panic" or (all_below_ma50 and (min_chg or 0) <= -1.5) or (min_chg is not None and min_chg <= -2.5):
                regime, label, max_penalty = "risk_off", "🔴 Risk-Off(系统性避险)", 12
            elif tier1_24h or vix_state == "elevated" or all_below_ma20 or (min_chg is not None and min_chg <= -1.5):
                regime, label, max_penalty = "caution", "🟠 Caution(逆风/宏观前夕)", 6
            elif (
                bms
                and all(b.get("above_ma20") is True and b.get("above_ma50") in (True, None) for b in bms)
                and (not vix or vix.get("level") is None or vix["level"] < 20)
                and not tier1_24h
                and not any_below_ma20
            ):
                regime, label, max_penalty = "risk_on", "🟢 Risk-On(顺风偏多)", 0
            else:
                regime, label, max_penalty = "neutral", "⚪ Neutral(震荡中性)", 0

        if vix and vix.get("level") is not None and vix_state != "calm":
            vchg = f"{vix['change_pct']:+.1f}%" if vix.get("change_pct") is not None else ""
            warnings.append(f"VIX {vix['level']:.2f}({vchg}, {vix_state})")
        for b in bms:
            if b.get("ext_gap_pct") is not None and b["ext_gap_pct"] <= -1.0:
                warnings.append(f"{b['symbol']} {b['source_label']}跳空 {b['ext_gap_pct']:+.2f}%")
            elif b.get("above_ma50") is False:
                warnings.append(f"{b['symbol']} 低于 MA50({b['ma50']})")
    else:
        bm = bms[0] if bms else None
        temp_val = to_float((mkt_temp or {}).get("temperature"))
        chg = bm.get("change_pct") if bm else None
        if bm is None and temp_val is None:
            regime, label, max_penalty = "unknown", "⚪ 未知(无大盘行情)", 0
        elif (chg is not None and chg <= -2.5) or (bm and bm.get("above_ma50") is False and (temp_val is not None and temp_val < 25)):
            regime, label, max_penalty = "risk_off", "🔴 Risk-Off(系统性避险)", 12
        elif tier1_24h or (bm and bm.get("above_ma20") is False) or (chg is not None and chg <= -1.5):
            regime, label, max_penalty = "caution", "🟠 Caution(逆风/宏观前夕)", 6
        elif bm and bm.get("above_ma20") is True and bm.get("above_ma50") in (True, None) and (temp_val is None or temp_val >= 50):
            regime, label, max_penalty = "risk_on", "🟢 Risk-On(顺风偏多)", 0
        else:
            regime, label, max_penalty = "neutral", "⚪ Neutral(震荡中性)", 0

    if tier1_24h:
        top_names = "、".join(e["name"].replace("美国, ", "")[:16] for e in tier1_24h[:2])
        warnings.append(f"24h内有 {len(tier1_24h)} 项 Tier-1 宏观数据({top_names})")
    elif tier1_recent:
        top_names = "、".join(e["name"].replace("美国, ", "")[:16] for e in tier1_recent[:2])
        warnings.append(f"刚公布 Tier-1 宏观数据({top_names}),关注市场消化")

    summary_parts = []
    if vix and vix.get("level") is not None:
        vchg = f"{vix['change_pct']:+.1f}%" if vix.get("change_pct") is not None else ""
        summary_parts.append(f"VIX {vix['level']:.2f}" + (f"({vchg})" if vchg else ""))
    for sym in bm_symbols:
        if sym in benchmarks:
            summary_parts.append(_short_bm_text(benchmarks[sym]))
    if mkt_temp:
        summary_parts.append(f"温度 {mkt_temp.get('temperature')} {market_temp_label(mkt_temp.get('temperature'))}")
    if tier1_24h:
        summary_parts.append(f"24h内Tier-1宏观 {len(tier1_24h)} 项")
    elif star3_upcoming:
        summary_parts.append(f"72h内3星宏观 {len(star3_upcoming)} 项")

    return {
        "market": mkt,
        "as_of": current.isoformat(timespec="minutes"),
        "regime": regime,
        "label": label,
        "max_bull_penalty": max_penalty,
        "vix": vix,
        "market_temp": mkt_temp,
        "benchmarks": benchmarks,
        "tier1_24h": tier1_24h,
        "tier1_48h": tier1_48h,
        "tier1_recent": tier1_recent,
        "star3_upcoming": star3_upcoming,
        "warnings": warnings,
        "summary": ", ".join(p for p in summary_parts if p),
    }


def fetch_market_regime(market: str = "US", output_json: bool = False) -> dict:
    result = assess_market_regime(market=market)
    if output_json:
        print_json(result)
        return result

    print(f"🧭 {result['market']} 大盘环境评估 (Market Regime)  [{result['as_of']}]")
    print("=" * 60)
    print(f"  综合状态: {result['label']}  (决策多头上限折减 {result['max_bull_penalty']} 分)")
    if result.get("vix") and result["vix"].get("level") is not None:
        v = result["vix"]
        chg = f"{v['change_pct']:+.2f}%" if v.get("change_pct") is not None else ""
        print(f"  恐慌指数: .VIX.US {v['level']:.2f} {chg}  [{v['state']}]")
    if result.get("market_temp"):
        t = result["market_temp"]
        print(f"  市场温度: {t.get('temperature')}/100 {market_temp_label(t.get('temperature'))}")
    print()

    bm_rows = []
    for sym, b in (result.get("benchmarks") or {}).items():
        if b.get("price") is None:
            continue
        pos = []
        for ma_k, lbl in (("above_ma20", "MA20"), ("above_ma50", "MA50"), ("above_ma200", "MA200")):
            if b.get(ma_k) is True:
                pos.append(f">{lbl}")
            elif b.get(ma_k) is False:
                pos.append(f"<{lbl}")
        bm_rows.append({
            "标的": sym,
            "现价": f"{b['price']:.2f}({b['source_label']})",
            "涨跌%": f"{b['change_pct']:+.2f}%" if b.get("change_pct") is not None else "-",
            "MA20": b.get("ma20") or "-",
            "MA50": b.get("ma50") or "-",
            "均线位置": " ".join(pos) or "-",
        })
    if bm_rows:
        print_display_table(bm_rows, columns=["标的", "现价", "涨跌%", "MA20", "MA50", "均线位置"])

    upcoming = result.get("star3_upcoming") or []
    recent = result.get("tier1_recent") or []
    if recent:
        print("\n  近期已公布 Tier-1 宏观数据:")
        for e in recent[:4]:
            print(f"    • {e['date']} {e['name']}  实际 {e['actual']} (预测 {e['estimate'] or '--'}, 前值 {e['previous'] or '--'})")
    if upcoming:
        print("\n  未来 72h 3星宏观日历:")
        rows = [{
            "分级": "🔥Tier-1" if e.get("tier") == "tier1" else "★★★",
            "事件": e["name"][:30],
            "时间": e["date"],
            "距今": f"{e['hours_until']:+.1f}h",
            "预测/前值": f"{e['estimate'] or '--'} / {e['previous'] or '--'}",
        } for e in upcoming[:8]]
        print_display_table(rows, columns=["分级", "事件", "时间", "距今", "预测/前值"])
    else:
        print("\n  未来 72h 无 3 星宏观催化事件。")

    if result.get("warnings"):
        print("\n  ⚠️ 风险提示: " + " | ".join(result["warnings"]))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="大盘环境状态评估 (Market Regime) + 宏观催化")
    parser.add_argument("--market", default="US", choices=["US", "HK", "CN", "SG"],
                        help="目标市场(默认 US)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_market_regime(market=args.market, output_json=args.output_json)
    except Exception as e:
        print_error("获取大盘环境", str(e))
        sys.exit(1)
