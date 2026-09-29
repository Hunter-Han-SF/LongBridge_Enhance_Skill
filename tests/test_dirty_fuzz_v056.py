"""v0.5.6 脏数据模糊回归(自查审计的沉淀)。

对每个脚本入口:把其依赖的 common 数据函数 mock 成「结构正确但数值被污染」
的数据(数值→0 / 字符串→空 / 标量→None),调用人类可读打印路径,断言不出现
未设防崩溃(TypeError/ZeroDivisionError/KeyError/…)。ValueError/RuntimeError
视为设计内的干净报错。

运行: python -m unittest tests.test_dirty_fuzz_v056 -v
"""
from __future__ import annotations

import contextlib
import io
import sys
import types
import unittest
from pathlib import Path

_HERE = Path(__file__).parent
_SCRIPTS = _HERE / ".." / "scripts"
for _sub in ("", "calendar", "decision", "flow", "fundamental", "intraday",
             "market", "quote", "screener", "sentiment", "technical"):
    sys.path.insert(0, str(_SCRIPTS / _sub))
sys.path.insert(0, str(_HERE))

import fixtures as FX  # noqa: E402
import calc_indicators  # noqa: E402
import common  # noqa: E402

OK_EXCEPTIONS = (ValueError, RuntimeError)

# ---------------------------------------------------------------- 干净夹具 --

def _bars(n=80, numeric=False):
    rows = []
    for i in range(n):
        row = {"open": 100 + i * 0.1, "close": 100.2 + i * 0.1, "high": 100.8 + i * 0.1,
               "low": 99.8 + i * 0.1, "volume": 10000 + i * 10, "timestamp": 1780000000 + i * 86400}
        if not numeric:
            row = {k: str(v) for k, v in row.items()}
        rows.append(row)
    return rows

def _chain():
    rows = []
    for k in range(80, 121, 5):
        rows.append({"strike": float(k), "call_iv": 0.32, "put_iv": 0.35,
                     "call_vol": 120, "put_vol": 130,
                     "call_last": 5.1, "put_last": 4.9})
    return rows

def _chain_oi():
    strikes = {}
    for k in range(80, 121, 5):
        strikes[float(k)] = {"call_oi": 10, "put_oi": 12, "call_gamma": 0.01,
                             "put_gamma": 0.011, "call_iv": 0.32, "put_iv": 0.35,
                             "call_delta": 0.5, "put_delta": -0.5}
    return {"oi_mode": True, "strikes": strikes,
            "total_call_oi": 10, "total_put_oi": 12, "pc_oi_ratio": 1.2,
            "strikes_queried": 9}

METRICS = {"delta": 0.5, "gamma": 0.02, "theta": -0.1, "vega": 0.08,
           "rho": 0.01, "oi": 100, "iv": 0.3}

def _contract_metrics(syms):
    return {s: dict(METRICS) for s in syms}

HIST = [{"date": f"2026-08-{d:02d}", "atm_iv_pct": 30.0 + (d % 5),
         "expiry": "2026-10-16", "strike": 100.0} for d in range(1, 29)]

F = {
    "get_kline": _bars(numeric=True),
    "get_kline_adjusted": _bars(numeric=True),
    "get_option_expirations": ["2026-10-16", "2026-11-20", "2026-12-18"],
    "get_option_chain": _chain(),
    "get_chain_oi": _chain_oi(),
    "get_option_contract_metrics": _contract_metrics,
    "get_option_volume_daily": [
        {"date": "2026-09-2" + str(i), "volume": "1000000", "call_volume": "600000",
         "put_volume": "400000", "call_oi": "5000", "put_oi": "4000"} for i in range(5)],
    "get_option_volume_realtime": {
        "call_volume": "600000", "put_volume": "400000", "ratio": "1.5",
        "total_volume": "1000000", "timestamp": "1787000000"},
    "get_underlying_price": 100.0,
    "get_atm_iv": 0.33,
    "get_anomaly": {"all_off": False, "changes": [
        {"counter_id": "ST/US/X", "name": "X", "emotion": 1, "content": "大涨",
         "timestamp": "1787000000", "market": "US"}] * 3},
    "get_top_movers": {"updated_at": "2026-09-28", "events": [
        {"stock": {"symbol": "X.US", "name": "X", "change": "0.03", "last_done": "100"},
         "alert_reason": "quick move"}] * 3},
    "get_capital_flow_snapshot": {
        "symbol": "X.US", "timestamp": "1787000000",
        "capital_in": {"large": 100.0, "medium": 50.0, "small": 25.0},
        "capital_out": {"large": 80.0, "medium": 40.0, "small": 20.0},
        "net": {"large": 20.0, "medium": 10.0, "small": 5.0, "total": 35.0},
        "unit_note": "n"},
    "get_capital_flow_series": [
        {"inflow": 100.0, "minute_delta": 1.0, "time": "10:00"} for _ in range(5)],
    "get_broker_holding_top": {
        "buy": [{"name": "MS", "parti_number": "5345", "chg": "0.1", "strong": "1"}],
        "sell": [{"name": "GS", "parti_number": "5337", "chg": "-0.1", "strong": "0"}],
        "updated_at": "2026-09-28"},
    "get_broker_holding_detail": {
        "list": [{"name": "MS", "parti_number": "5345", "strong": "1",
                  "ratio": {"value": "0.1", "chg_1": "0.01"},
                  "shares": {"value": "1000", "chg_1": "100"}}],
        "updated_at": "2026-09-28"},
    "get_short_trades": {
        "symbol": "X.US", "sources": "n", "market": "US",
        "data": [{"nus_amount": "1000", "ny_amount": "2000", "total_amount": "3000",
                  "rate": "0.5", "close": "100", "timestamp": "1787000000"}] * 3},
    "get_short_positions": {
        "symbol": "X.US", "sources": "n", "market": "US",
        "data": [{"current_shares_short": "1000", "rate": "0.5", "days_to_cover": "2",
                  "close": "100", "timestamp": "1787000000"}] * 3},
    "get_finance_calendar": FX.CAL_SPLIT["list"],
    "get_market_temp": {"temperature": 55, "valuation": "50%", "sentiment": "中性",
                        "description": "n"},
    "get_heat_rank_keys": [{"key": "hot_all-us", "name": "全部"}],
    "get_heat_rank": {"bmp": None, "updated_at": "2026-09-28", "lists": [
        {"symbol": "X.US", "name": "X", "last_done": "311", "chg": "0.012",
         "ticker": "X"}] * 3},
    "get_intraday": [{"price": "100.1", "avg_price": "100.0", "timestamp": "1787000000"}
                     for _ in range(120)],
    "get_depth": {"bids": [{"position": i + 1, "price": f"{99.9 - i * 0.1:.2f}",
                            "volume": 100 * (i + 1)} for i in range(5)],
                  "asks": [{"position": i + 1, "price": f"{100.1 + i * 0.1:.2f}",
                            "volume": 100 * (i + 1)} for i in range(5)]},
    "get_trades": [{"price": "100.1", "buy_amount": "3500", "neutral_amount": "100",
                    "sell_amount": "2100", "timestamp": "1787000000"} for _ in range(10)],
    "get_valuation": {
        "overview": {"metrics": {"pe": {"desc": "市盈率", "circle": "n"}}},
        "history": {"metrics": {"pe": {"list": [
            {"timestamp": "1780000000", "value": "25.0"}] * 5,
            "median": "22.0", "high": "40.0", "low": "12.0"}}},
        "peers": {"pe": {"industry_median": "20.0", "list": [
            {"counter_id": "ST/US/X", "name": "X", "value": "25.0"}] * 3}}},
    "get_institution_rating": {
        "analyst": {"evaluate": {"buy": 10, "over": 20, "hold": 5, "under": 2,
                                 "sell": 1, "no_opinion": 0, "total": 38},
                    "target": {"highest_price": "150", "lowest_price": "80",
                               "prev_close": "100"},
                    "industry_name": "电子", "industry_rank": "5",
                    "industry_total": "50"},
        "instratings": {"list": []}},
    "get_forecast_eps": [
        {"forecast_eps_mean": "2.2", "forecast_eps_highest": "3.0",
         "forecast_eps_lowest": "1.5", "forecast_eps_median": "2.2",
         "forecast_start_date": "1780000000", "forecast_end_date": "1790000000",
         "institution_up": "10", "institution_down": "2",
         "institution_total": "12"}] * 2,
    "get_financial_report": {
        "list": {"IS": {"indicators": [
            {"accounts": [
                {"name": "营业收入", "ranking_code": "n", "ratio": "1.2",
                 "values": [{"period": "2026Q2", "year": "2026", "value": "100",
                             "yoy": "0.1"}] * 3}] * 2}]}}},
    "get_dividend_history": [
        {"symbol": "X.US", "ex_date": f"2026.{m:02d}.10", "record_date": "",
         "payment_date": "", "desc": "每股派息 0.25 USD", "amount": 0.25,
         "currency": "USD"} for m in (2, 5, 8, 11)],
    "get_warrant_list": FX.WARRANT_LIST,
    "get_warrant_quote": FX.WARRANT_QUOTE,
    "get_warrant_issuers": FX.WARRANT_ISSUERS,
    "get_screener_strategies": FX.SCREENER_STRATEGIES,
    "run_screener_strategy": FX.SCREENER_RUN["items"],
    "screener_filter": FX.SCREENER_FILTER,
    "get_screener_indicators": FX.SCREENER_INDICATORS,
    "get_broker_queue": FX.BROKERS_QUEUE,
    "get_participants": FX.PARTICIPANTS,
    "get_ipo_listings": FX.IPO_WAIT_LISTING,
    "get_ipo_detail": FX.IPO_DETAIL,
    "get_macro_indicators": FX.MACRO_LIST,
    "get_macro_history": FX.MACRO_HISTORY["data"],
    "compare_stocks": FX.COMPARE["list"],
    "get_business_segments": FX.SEGMENTS["business"],
    "get_industry_rank": FX.INDUSTRY_RANK["items"],
    "get_industry_peers": FX.INDUSTRY_PEERS,
    "get_industry_valuation_dist": FX.INDUSTRY_VALUATION_DIST,
    "get_consensus": FX.CONSENSUS,
    "get_corp_actions": FX.CORP_ACTIONS["items"],
    "get_operating": FX.OPERATING["list"],
    "get_company_profile": FX.COMPANY,
    "get_executives": FX.EXECUTIVES["professional_list"],
    "get_insider_trades": FX.INSIDER_TRADES,
    "get_investor_rankings": FX.INVESTOR_RANKINGS,
    "get_investor_holdings": FX.INVESTOR_HOLDINGS,
    "get_investor_changes": FX.INVESTOR_CHANGES,
    "get_fund_holders": FX.FUND_HOLDERS["lists"],
    "get_shareholders": FX.SHAREHOLDERS["shareholder_list"],
    "get_ah_premium": FX.AH_PREMIUM["klines"],
    "get_ah_premium_intraday": FX.AH_PREMIUM_INTRADAY["klines"],
    "get_constituent": FX.CONSTITUENT,
    "get_trade_stats": FX.TRADE_STATS,
}

# ---------------------------------------------------------------- 变异器 --

def _is_num_str(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False

def mutate(obj, mode):
    if isinstance(obj, list):
        return [mutate(x, mode) for x in obj]
    if isinstance(obj, dict):
        return {k: mutate(v, mode) for k, v in obj.items()}
    if callable(obj) and not isinstance(obj, str):
        return obj  # side_effect 函数不变异
    if mode == "zero":
        if isinstance(obj, bool):
            return obj
        if isinstance(obj, (int, float)):
            return 0
        if isinstance(obj, str) and _is_num_str(obj):
            return "0"
    if mode == "empty":
        if isinstance(obj, str):
            return ""
    if mode == "none":
        if obj is None or isinstance(obj, (str, int, float)) and not isinstance(obj, bool):
            return None
    return obj

# ---------------------------------------------------------------- 用例表 --

def _ns(**kw):
    d = {"lookback": 250, "max_stop_pct": 0.08, "sector_top_decline": None,
         "recent_stopout": None, "familiar": None, "prepost_move": None,
         "sector_breakout": None, "earnings_days": None, "no_heat": False,
         "smallcap_usd": 3e9, "now": None, "sector": None, "sector_chg_pct": 2.0,
         "output_json": False}
    d.update(kw)
    return types.SimpleNamespace(**d)

def case(mod, fname, args=(), kwargs=None, extra_mocks=None, skip_fns=()):
    return {"mod": mod, "call": lambda m: getattr(m, fname)(*args, **(kwargs or {})),
            "extra": extra_mocks or {}, "skip": set(skip_fns)}

CASES = [
    case("get_closed_calendar", "fetch_closed_calendar", kwargs={"market": "US", "count": 5, "output_json": False}),
    case("get_dividend_calendar", "fetch_dividend_calendar", kwargs={"market": "US", "symbol": "AAPL.US", "watchlist": None, "count": 10, "output_json": False}),
    case("get_earnings_calendar", "fetch_earnings_calendar", kwargs={"market": "US", "symbol": "AAPL.US", "watchlist": None, "count": 10, "output_json": False}),
    case("get_ipo_calendar", "fetch_ipo_calendar", kwargs={"market": "US", "start": None, "end": None, "count": 10, "output_json": False}),
    case("get_ipo_detail", "fetch_ipo_detail", ("3223.HK",), {"output_json": False}),
    case("get_ipo_listings", "fetch_ipo_listings", kwargs={"stage": "wait-listing", "output_json": False}),
    case("get_macro_calendar", "fetch_macro_calendar", kwargs={"market": "US", "start": None, "end": None, "count": 10, "output_json": False}),
    case("get_split_calendar", "fetch_split_calendar", kwargs={"market": "US", "symbol": "AAPL.US", "watchlist": None, "count": 10, "output_json": False}),
    case("analyze_buy_sell", "analyze", ("AAPL.US",), {"output_json": False}),
    case("check_entry_rules", "analyze", ("AAPL.US", _ns())),
    case("get_broker_holding", "fetch_broker_holding", ("700.HK",), {"period": "rct_1", "detail": False, "output_json": False}),
    case("get_broker_queue", "fetch_broker_queue", ("700.HK",), {"levels": 5, "output_json": False}),
    case("get_capital_flow", "fetch_capital_flow", ("AAPL.US",), {"flow": False, "output_json": False}),
    case("get_short_sale", "fetch_short_sale", ("AAPL.US",)),
    case("compare_stocks", "fetch_compare", (["AAPL.US", "MSFT.US"],), {"currency": "USD", "output_json": False}),
    case("get_analyst_consensus", "analyze", ("AAPL.US",), {"output_json": False}),
    case("get_business_segments", "fetch_business_segments", ("AAPL.US",), {"output_json": False}),
    case("get_company_profile", "fetch_company_profile", ("AAPL.US",), {"execs_count": 5, "output_json": False}),
    case("get_consensus", "fetch_consensus", ("AAPL.US",), {"count": 6, "output_json": False}),
    case("get_corp_actions", "fetch_corp_actions", ("AAPL.US",), {"count": 10, "output_json": False}),
    case("get_dividend_quality", "analyze", ("AAPL.US",), {"output_json": False}),
    case("get_financial_health", "analyze", ("AAPL.US",), {"output_json": False}),
    case("get_fund_holders", "fetch_fund_holders", ("AAPL.US",), {"count": 10, "output_json": False}),
    case("get_industry_rank", "fetch_industry_rank", kwargs={"market": "US", "peers": None, "valuation": None, "output_json": False}),
    case("get_insider_trades", "fetch_insider_trades", ("TSLA.US",), {"count": 10, "output_json": False}),
    case("get_institutional_holdings", "fetch_institutional_holdings", kwargs={"cik": "0001422848", "changes": False, "count": 10, "output_json": False}),
    case("get_operating", "fetch_operating", ("AAPL.US",), {"count": 4, "output_json": False}),
    case("get_shareholders", "fetch_shareholders", ("AAPL.US",), {"count": 10, "output_json": False}),
    case("get_valuation_percentile", "analyze", ("AAPL.US",), {"output_json": False}),
    case("get_orderbook_pressure", "analyze", ("AAPL.US",), {"output_json": False}),
    case("get_trade_flow", "analyze", ("AAPL.US",), {"count": 200, "big_size": 100000, "output_json": False}),
    case("get_trade_stats", "fetch_trade_stats", ("AAPL.US",), {"output_json": False}),
    case("get_vwap_analysis", "analyze", ("AAPL.US",), {"date": None, "output_json": False}),
    case("calc_anomaly_score", "calc_score", ("AAPL.US",), {"market": "US", "output_json": False}),
    case("get_ah_premium", "fetch_ah_premium", ("700.HK",), {"count": 10, "kline_type": "day", "output_json": False}),
    case("get_anomaly", "fetch_anomaly", kwargs={"market": "US", "symbol": None, "count": 20, "output_json": False}),
    case("get_constituent", "fetch_constituent", ("HKHSI",), {"limit": 20, "sort": "volume", "order": "desc", "output_json": False}),
    case("get_top_movers", "fetch_top_movers", kwargs={"market": "US", "sort": "hot", "count": 10, "output_json": False}),
    case("analyze_iv_crush", "analyze_iv_crush", ("AAPL.US",), {"output_json": False}),
    case("calc_exercise_prob", "exercise_prob", ("AAPL.US", "2026-12-18", 100.0, "CALL")),
    case("calc_expected_move", "analyze", ("AAPL.US",), {"date": "2026-11-20", "show_all": False, "output_json": False}),
    case("calc_gamma_profile", "analyze", ("AAPL.US",), {"window_days": 60, "range_pct": 0.1, "output_json": False}),
    case("calc_gex", "calc_gex", ("AAPL.US", "2026-11-20"), {"rate": 0.045, "output_json": False}),
    case("calc_iv_percentile", "calc_iv_percentile", ("AAPL.US",), {"min_points": 5, "output_json": False}),
    case("calc_iv_rank", "calc_iv_rank", ("AAPL.US",), {"min_points": 5, "output_json": False}),
    case("calc_max_pain", "analyze", ("AAPL.US",), {"date": "2026-11-20", "output_json": False}),
    case("calc_risk_reversal", "analyze", ("AAPL.US",), {"date": "2026-11-20", "target_delta": 0.25, "rate": 0.045, "output_json": False}),
    case("get_iv_term_structure", "analyze", ("AAPL.US",), {"count": 6, "output_json": False}),
    case("get_option_chain", "get_chain", ("AAPL.US", "2026-11-20"), {"near_atm": False, "atm_range": 0.05, "output_json": False}),
    case("get_option_expiration", "get_option_expiration", ("AAPL.US",), {"limit": 10, "output_json": False}),
    case("get_option_oi", "analyze", ("AAPL.US",), {"date": "2026-11-20", "near_atm_pct": 0.1, "max_strikes": 20, "output_json": False}),
    case("get_option_quote", "get_quote", ("AAPL.US", "2026-11-20", 100.0, "CALL")),
    case("get_option_strategy", "build_strategy", ("AAPL.US", "2026-11-20", "bull_call_spread"), {"otm_pct": 0.05, "output_json": False}),
    case("get_option_volatility", "analyze", ("AAPL.US",), {"expiry": "2026-11-20", "hv_days": 30, "option_type": "CALL", "output_json": False}),
    case("get_option_volume", "get_volume", ("AAPL.US",), {"daily": True, "count": 10, "output_json": False}),
    case("get_put_call_wall", "analyze_walls", ("AAPL.US", "2026-11-20"), {"walls": 3, "output_json": False}),
    case("get_vol_smile", "smile", ("AAPL.US",), {"expiry": "2026-11-20", "near_atm": True, "atm_range": 0.1, "output_json": False}),
    case("get_warrant", "fetch_warrant", ("700.HK",), {"quote": False, "issuers": False, "sort": "expiry", "count": 10, "enrich": 0, "direction": None, "output_json": False}),
    case("resolve_option_code", "resolve", ("AAPL.US", "2026-11-20", 100, "CALL")),
    case("run_screener", "fetch_screener", kwargs={"run": 19, "conditions": None, "market": "HK", "output_json": False}),
    case("daily_briefing", "generate_briefing", kwargs={"market": "US", "include_pc": True, "output_json": False}),
    case("get_heat_rank", "fetch_heat_rank", kwargs={"market": "US", "key": "hot_all-us", "count": 10, "output_json": False}),
    case("get_macro_data", "fetch_macro_data", kwargs={"code": "30771936", "keyword": None, "country": None, "page": 1, "count": 12, "start": None, "end": None, "output_json": False}),
    case("get_market_temp", "fetch_market_temp", kwargs={"market": "US", "history": False, "start": None, "end": None, "output_json": False}),
    case("calc_indicators", "show_indicators", ("AAPL.US",), {"count": 80, "output_json": False}, skip_fns=("get_kline_adjusted",)),
    case("calc_relative_strength", "analyze", ("AAPL.US",), {"benchmark": ".INX", "count": 120, "output_json": False}),
    case("calc_technical_score", "score", ("AAPL.US",), {"count": 80, "output_json": False}),
    case("run_quant_indicator", "fetch_quant_indicator", ("AAPL.US",), {"preset": "full", "start": None, "end": None}),
]

_QUANT_RESULT = {"series": {"EMA20": [10.0, 11.0], "RSI": [55.0, 62.0]}}
for _c in CASES:
    if _c["mod"] in ("calc_indicators", "calc_technical_score", "calc_relative_strength"):
        _c["extra"]["calc_indicators.get_kline_adjusted"] = F["get_kline_adjusted"]
    if _c["mod"] == "run_quant_indicator":
        _c["extra"]["run_quant_script"] = _QUANT_RESULT
        _c["extra"]["calc_indicators.get_kline_adjusted"] = F["get_kline_adjusted"]
    if _c["mod"] in ("calc_iv_rank", "calc_iv_percentile"):
        _c["extra"]["_build_series"] = {"series": HIST, "date_range": "a~b", "data_points": len(HIST)}
    if _c["mod"] == "get_iv_history":
        _c["extra"]["_load_history"] = HIST
    if _c["mod"] == "get_option_quote":
        _c["extra"]["run_cli"] = None

# ---------------------------------------------------------------- 驱动 --

_MODULES = {}

def _mod(name):
    if name not in _MODULES:
        _MODULES[name] = __import__(name)
    return _MODULES[name]


def module_imports_of(mod):
    import re
    src = Path(mod.__file__).read_text(encoding="utf-8")
    m = re.search(r"from common import \(  # noqa: E402\n((?:    [^\n]+\n)+)\)", src)
    if not m:
        return []
    names = []
    for line in m.group(1).split("\n"):
        for n in line.strip().split(","):
            n = n.strip()
            if n and not n.startswith("#"):
                names.append(n)
    return names


def _mk(v):
    if callable(v) and not isinstance(v, str):
        return v
    return lambda *a, **k: v


# 数值级污染(zero/empty/none)。drop(删键)会破坏 common getter 构造时即
# 保证的顶层字段(如 get_anomaly 的 all_off、get_chain_oi 的 strikes),
# 产生现实里不可能的输入,故不用于回归。calc_iv_rank/percentile 的序列
# 来自本地自写文件(值恒为 float),none 模式同样不属于现实输入。
_MODES_DEFAULT = ("zero", "empty", "none")
_MODES_OVERRIDES = {
    "calc_iv_rank": ("zero", "empty"),
    "calc_iv_percentile": ("zero", "empty"),
}


def _modes_for(mod_name):
    return _MODES_OVERRIDES.get(mod_name, _MODES_DEFAULT)


class TestDirtyDataNoCrash(unittest.TestCase):
    """每个脚本入口在数值级脏数据(0/空串/None)下不得未设防崩溃。

    ValueError/RuntimeError 视为设计内的干净报错(交由 CLI 层 print_error)。
    """

    def _run_case(self, c, mode):
        mod = _mod(c["mod"])
        imports = module_imports_of(mod)
        mock_names = [n for n in imports if n in F and n not in c["skip"]]
        saved = {n: getattr(mod, n) for n in mock_names}
        extra_saved = {}
        try:
            mocks = {n: mutate(F[n], mode) for n in mock_names}
            for k, v in c["extra"].items():
                if k == "calc_indicators.get_kline_adjusted":
                    target, attr = calc_indicators, "get_kline_adjusted"
                else:
                    target, attr = mod, k
                extra_saved[(target, attr)] = getattr(target, attr, None)
                setattr(target, attr, _mk(mutate(v, mode) if not callable(v) else v))
            for n, v in mocks.items():
                setattr(mod, n, _mk(v))
            buf_o, buf_e = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf_o), contextlib.redirect_stderr(buf_e):
                c["call"](mod)
        except OK_EXCEPTIONS:
            pass
        finally:
            for n, old in saved.items():
                setattr(mod, n, old)
            for (target, attr), old in extra_saved.items():
                setattr(target, attr, old)


def _make_test(c):
    def test(self):
        for mode in _modes_for(c["mod"]):
            with self.subTest(mode=mode):
                self._run_case(c, mode)
    test.__doc__ = f"{c['mod']} 数值级脏数据不崩溃"
    return test


for _c in CASES:
    setattr(TestDirtyDataNoCrash, f"test_{_c['mod']}_dirty_data", _make_test(_c))


class TestUnitGuards(unittest.TestCase):
    """单个修复点的直接回归。"""

    def test_calc_hv_skips_none_closes(self):
        # None 收盘价整对跳过:有效对 <2 → None;≥2 → 正常出值不崩溃
        self.assertIsNone(common.calc_hv([100.0, None, 102.0]))
        self.assertGreater(common.calc_hv([100.0, None, 110.0, 121.0, 132.0], annualize=1), 0)

    def test_entry_rules_filters_dirty_bars(self):
        import check_entry_rules as cer
        bars = _bars(numeric=True)[:40]
        for i in (5, 17, 30):
            bars[i]["close"] = None      # 整根应被剔除
        bars[22] = {}                    # 缺键整根应被剔除
        f = cer.build_features(bars)
        self.assertEqual(f["n"], 36)     # 40 - 4 根脏数据

    def test_entry_rules_atr_pct_zero_last(self):
        import check_entry_rules as cer
        bars = [{"open": 0.0, "close": 0.0, "high": 0.0, "low": 0.0, "volume": 0}
                for _ in range(40)]
        f = cer.build_features(bars)     # 全 0 收盘:不得 ZeroDivision
        self.assertEqual(f["atr_pct"], 0.0)

    def test_dividend_calendar_none_name(self):
        import get_dividend_calendar as gdc
        infos = [{"counter_id": "ST/US/X", "counter_name": None, "date": "2026.09.30",
                  "content": "每股派息 0.1 USD", "data_kv": [], "ext": {},
                  "symbol": "X.US", "name": None, "ex_date": "2026.09.30",
                  "amount": 0.1, "currency": "USD"}]
        orig = gdc.get_finance_calendar
        try:
            gdc.get_finance_calendar = lambda **k: [{"date": "2026-09-30",
                                                     "count": 1, "infos": infos}]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = gdc.fetch_dividend_calendar(market="US", symbol="X.US",
                                                watchlist=None, count=5,
                                                output_json=False)
            self.assertIsInstance(r, dict)
        finally:
            gdc.get_finance_calendar = orig

    def test_broker_queue_none_names(self):
        import get_broker_queue as gbq
        orig_p, orig_q = gbq.get_participants, gbq.get_broker_queue
        try:
            gbq.get_participants = lambda: [{"broker_id": "1", "name_cn": None,
                                             "name_en": None}]
            gbq.get_broker_queue = lambda s: {"bids": [{"position": 1, "broker_ids": [1]}],
                                              "asks": []}
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = gbq.fetch_broker_queue("700.HK", levels=5, output_json=False)
            self.assertIsInstance(r, dict)
        finally:
            gbq.get_participants, gbq.get_broker_queue = orig_p, orig_q


if __name__ == "__main__":
    unittest.main()
