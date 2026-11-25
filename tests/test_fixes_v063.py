"""v0.6.3 修复回归:2026-11-24 第六轮审计的中优先级 6 项。

夹具取自 2026-11-24/25 的实盘数据(CLI 0.27.1):
  1. 盘中量比: 美股常规时段内日 K 带着当日未收盘的 bar(09:31 ET 成交量 214 万,
     约为全天的 4.5%),量比 0.07 被判「缩量」。
     修复: 未收盘 bar 的成交量视为未定(量比不算),OBV/MFI 用已收盘的 K 线,
           技术面评分按可得满分 95 折算,入场规则把量能类条件按未知处理。
  2. 零成交腿: chain 只有 last,行权价当日无成交时 last=0(AAPL 2026-12-04 的 80 档
     里有 16 档),被当成免费期权。
     修复: 依次用腿内 price → chain last(>0) → chain IV 的 BS 估算,都没有则报错。
  3. 现价来源: 常规时段之外 quote 的 last 是上一个常规时段的收盘价(实测 AAPL
     last=349.08,盘前 347.80),无任何标注。
     修复: get_underlying_price 取最新时段的价格并记录来源;价格要与期权链 IV /
           日 K 对齐的场合改用常规时段价;各脚本输出标注来源。
  4. D12: 休市日历里的半日市(2026-11-27 感恩节翌日,holiday_type=half_day)被当成
     休市日,盘前 9:00-9:30 误报放行。
     修复: 只有全日休市才算休市日。
  5. 美股沽空占比: FINRA 每日空头成交量占比含做市对冲,各股常态水平不同(实测
     17%~58%),强生 53% 被标「做空极活跃」、仪表盘扣 10 分。
     修复: 美股只报数值并与自身此前均值比较,不套港股阈值、不计分。
  6. 美股盘口: 美股默认行情为 LV1,depth 只有买一/卖一(港股 10 档),拿 2 股对
     37 股得出「卖盘显著占优」。
     修复: 买卖两侧不足 5 档时不下结论、不给挂单墙和加权中枢。

运行: python -m unittest tests.test_fixes_v063 -v
"""
from __future__ import annotations

import contextlib
import inspect
import io
import math
import os
import sys
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "decision", "flow", "fundamental", "intraday", "quote", "technical"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))

import common  # noqa: E402
import analyze_buy_sell  # noqa: E402
import calc_indicators  # noqa: E402
import calc_option_pnl  # noqa: E402
import calc_technical_score  # noqa: E402
import check_entry_rules as entry  # noqa: E402
import get_analyst_consensus  # noqa: E402
import get_iv_history  # noqa: E402
import get_orderbook_pressure as orderbook  # noqa: E402
import get_short_sale  # noqa: E402


def _run(func, *args, **kwargs):
    """调用会打印的入口并吞掉 stdout,返回结果。"""
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


def _capture(func, *args, **kwargs):
    """返回 (结果, 标准输出文本)。"""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = func(*args, **kwargs)
    return result, buffer.getvalue()


EST = timezone(timedelta(hours=-5))  # 2026-11 的美东时间(冬令时)


def et(month, day, hour, minute=0):
    return datetime(2026, month, day, hour, minute, tzinfo=EST)


def ramp(start: float, chg: float, n: int) -> list[float]:
    """从 start 起每根涨(chg>0)/跌(chg<0) chg 比例。"""
    out, p = [], start
    for _ in range(n):
        p *= 1 + chg
        out.append(p)
    return out


def daily_bars(closes: list[float], volume: float = 1_000_000.0, last_volume=None) -> list[dict]:
    """按收盘序列生成日 K(开=前收,高/低略超出实体),时间戳为美股日 K 的 ISO 形态。"""
    bars, prev = [], closes[0]
    day = datetime(2026, 6, 1)
    for i, px in enumerate(closes):
        eps = 1e-6 * i
        last = i == len(closes) - 1
        bars.append({"time": (day + timedelta(days=i)).strftime("%Y-%m-%dT05:00:00Z"),
                     "open": prev, "close": px, "high": max(prev, px) * (1.003 + eps),
                     "low": min(prev, px) * (0.997 - eps),
                     "volume": last_volume if last and last_volume is not None else volume})
        prev = px
    return bars


class _StashCase(unittest.TestCase):
    """每个用例前后清空正股价格来源缓存,避免用例间串扰。"""

    def setUp(self):
        common._LAST_PRICE_INFO.clear()
        self.addCleanup(common._LAST_PRICE_INFO.clear)


# --------------------------------------------------------------------------- #
# 1. 现价来源: 常规时段之外 last 是昨收
# --------------------------------------------------------------------------- #

def aapl_quote(pre_last="347.80", pre_stamp="2026-11-24T14:16:31Z", post=None, overnight=None):
    """2026-11-24 盘前的 AAPL quote(实测 last=349.08 是上一常规时段的收盘价,盘前 347.80)。"""
    quote = {"symbol": "AAPL.US", "last": "349.08", "prev_close": "350.20", "status": "Normal"}
    if pre_last:
        quote["pre_market"] = {"last": pre_last, "timestamp": pre_stamp, "prev_close": "350.20"}
    if post:
        quote["post_market"] = post
    if overnight:
        quote["overnight"] = overnight
    return [quote]


PRE_INFO = {"price": 347.80, "source": "pre_market", "source_label": "盘前",
            "time": datetime(2026, 11, 24, 14, 16, 31, tzinfo=timezone.utc),
            "regular_price": 349.08}
PRE_NOTE = "(盘前价 美东 09:16,常规时段收盘 349.08)"


class TestLatestPriceInExtendedHours(_StashCase):
    """盘前/盘后/夜盘:延长时段有更新的报价就用它,并记录来源;常规时段内仍是 last。"""

    def _price(self, now, quote, symbol="AAPL.US", **kwargs):
        orig = common.market_now
        common.market_now = lambda market, at=None, **kw: now  # 形参不能叫 now,否则遮蔽闭包
        try:
            with unittest.mock.patch.object(common, "run_cli", return_value=quote):
                return common.get_underlying_price(symbol, **kwargs)
        finally:
            common.market_now = orig

    def test_premarket_price_beats_prior_regular_close(self):
        """修复前只读 last → 349.08(昨收),盘前的 347.80 被丢弃。"""
        with unittest.mock.patch.object(common, "run_cli", return_value=aapl_quote()):
            quote = common.get_underlying_quote("AAPL.US")
        self.assertEqual(quote["regular_price"], 349.08)
        self.assertEqual([item["source"] for item in quote["extended"]], ["pre_market"])
        price, info = common.latest_underlying_price(quote, now=et(11, 24, 9, 20))
        self.assertEqual(price, 347.80)
        self.assertEqual((info["source"], info["regular_price"]), ("pre_market", 349.08))

    def test_get_price_records_source_and_note(self):
        self.assertEqual(self._price(et(11, 24, 9, 20), aapl_quote()), 347.80)
        self.assertEqual(common.get_underlying_price_info("AAPL.US")["source"], "pre_market")
        self.assertEqual(common.price_source_note("AAPL.US"), PRE_NOTE)
        # 只读、不请求 CLI
        with unittest.mock.patch.object(common, "run_cli", side_effect=AssertionError("不应请求 CLI")):
            self.assertEqual(common.price_source_note("AAPL.US"), PRE_NOTE)
        self.assertEqual(common.price_source_note("MSFT.US"), "")  # 没取过价的标的

    def test_regular_session_uses_last_and_notes_nothing(self):
        self.assertEqual(self._price(et(11, 24, 10, 0), aapl_quote()), 349.08)
        self.assertEqual(common.get_underlying_price_info("AAPL.US")["source"], "regular")
        self.assertEqual(common.price_source_note("AAPL.US"), "")

    def test_post_market_price_after_close(self):
        post = {"last": "349.50", "timestamp": "2026-11-25T01:30:00Z"}  # 20:30 ET
        self.assertEqual(self._price(et(11, 24, 21, 0), aapl_quote(post=post)), 349.50)
        self.assertEqual(common.price_source_note("AAPL.US"), "(盘后价 美东 20:30,常规时段收盘 349.08)")

    def test_extended_quote_older_than_last_close_is_not_used(self):
        """盘前块还是当天早上(早于 16:00 收盘)的旧报价时,不能拿它当收盘后的现价。"""
        self.assertEqual(self._price(et(11, 24, 17, 0), aapl_quote()), 349.08)
        self.assertEqual(common.price_source_note("AAPL.US"), "")

    def test_small_clock_skew_is_tolerated_but_not_future_quotes(self):
        near = {"last": "349.10", "timestamp": "2026-11-24T22:02:00Z"}   # 比本机快 2 分钟
        far = {"last": "349.20", "timestamp": "2026-11-24T22:30:00Z"}   # 晚 30 分钟:不是当前报价
        self.assertEqual(self._price(et(11, 24, 17, 0), aapl_quote(post=near)), 349.10)
        self.assertEqual(self._price(et(11, 24, 17, 0), aapl_quote(post=far)), 349.08)

    def test_regular_session_price_for_option_chain_alignment(self):
        """chain 的 IV 是上一常规时段的:选 ATM 要用常规时段价,不用盘前价。"""
        with unittest.mock.patch.object(common, "run_cli", return_value=aapl_quote()):
            self._price(et(11, 24, 9, 20), aapl_quote())
            self.assertEqual(common.regular_session_price("AAPL.US", 347.80), 349.08)
            self.assertEqual(common.get_underlying_price("AAPL.US", session="regular"), 349.08)
            self.assertEqual(common.get_underlying_price_info("AAPL.US")["source"], "regular")
            self.assertEqual(common.regular_session_price("AAPL.US", 349.08), 349.08)  # 常规时段内不再取价

    def test_non_us_market_reads_last(self):
        quote = [{"symbol": "0700.HK", "last": "344.200", "pre_market": None}]
        self.assertEqual(self._price(et(11, 24, 9, 20), quote, symbol="0700.HK"), 344.20)
        self.assertEqual(common.get_underlying_price_info("0700.HK")["source"], "regular")


class TestIvHistoryUsesRegularPrice(_StashCase):
    """盘前运行 get_iv_history:ATM 按常规时段价选(与 IV 同一时点)。"""

    CHAINS = {
        "2026-12-04": [{"strike": "347", "call_iv": "0.300", "put_iv": "0.300"},
                       {"strike": "350", "call_iv": "0.280", "put_iv": "0.280"}],
        "2027-01-15": [{"strike": "349", "call_iv": "0.310", "put_iv": "0.310"}],
    }
    DAYS = {"2026-12-04": 10 / 365, "2027-01-15": 52 / 365}

    def test_atm_follows_regular_price_not_premarket_price(self):
        names = ("get_underlying_price", "get_option_expirations", "get_option_chain", "days_to_years")
        orig = tuple(getattr(get_iv_history, name) for name in names)
        get_iv_history.get_underlying_price = lambda s: 347.80  # 盘前价
        get_iv_history.get_option_expirations = lambda s: list(self.CHAINS)
        get_iv_history.get_option_chain = lambda u, e: self.CHAINS[e]
        get_iv_history.days_to_years = lambda expiry, today=None, **kw: self.DAYS[expiry]
        common._LAST_PRICE_INFO["AAPL.US"] = dict(PRE_INFO)
        try:
            with unittest.mock.patch.object(common, "run_cli", return_value=aapl_quote(pre_last=None)):
                iv, meta = get_iv_history.get_current_atm_iv("AAPL.US")
        finally:
            for name, value in zip(names, orig):
                setattr(get_iv_history, name, value)
        self.assertEqual(meta["source_expiries"][0]["strike"], 350)  # 修复前按 347.80 选到 347
        self.assertAlmostEqual(iv, 0.305, places=3)


class TestPriceSourceLabel(_StashCase):
    """打印「现价」的脚本都要带上来源后缀,JSON 里带 underlying_price_source。"""

    def test_consensus_header_labels_premarket_price(self):
        common._LAST_PRICE_INFO["AAPL.US"] = dict(PRE_INFO)
        rating = {"analyst": {"evaluate": {"buy": 20, "over": 5, "hold": 3, "under": 1,
                                           "sell": 0, "total": 29},
                              "target": {"highest_price": "425", "lowest_price": "250"}}}
        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(
                get_analyst_consensus, "get_institution_rating", lambda s: rating))
            stack.enter_context(unittest.mock.patch.object(
                get_analyst_consensus, "get_forecast_eps", lambda s: []))
            stack.enter_context(unittest.mock.patch.object(
                get_analyst_consensus, "get_underlying_price", lambda s: 347.80))
            result, out = _capture(get_analyst_consensus.analyze, "AAPL.US")
            result_json = _run(get_analyst_consensus.analyze, "AAPL.US", output_json=True)
        self.assertIn(f"现价 347.8{PRE_NOTE}", out)
        self.assertEqual(result["underlying_price_source"]["source"], "pre_market")
        self.assertEqual(result_json["underlying_price_source"]["source"], "pre_market")

    def test_every_spot_price_script_is_wired(self):
        """源码层面的接线检查:每个取正股价的脚本都调用 price_source_note 并输出来源字段。"""
        modules = ("analyze_buy_sell", "calc_expected_move", "calc_gamma_profile", "calc_gex",
                   "calc_max_pain", "calc_option_pnl", "calc_risk_reversal", "get_dividend_quality",
                   "get_iv_term_structure", "get_option_oi", "get_option_quote", "get_option_strategy",
                   "get_option_volatility", "get_put_call_wall", "get_vol_smile")
        for name in modules + ("calc_exercise_prob", "get_analyst_consensus"):
            with self.subTest(module=name):
                source = inspect.getsource(__import__(name))
                self.assertIn('"underlying_price_source": get_underlying_price_info(', source)
        # calc_risk_reversal 只有 JSON 输出,没有文本行的「现价」
        for name in modules:
            if name != "calc_risk_reversal":
                with self.subTest(module=name, kind="text"):
                    self.assertIn("{price_source_note(", inspect.getsource(__import__(name)))


# --------------------------------------------------------------------------- #
# 2. 盘中量比: 当日未收盘的 bar
# --------------------------------------------------------------------------- #

class TestBarInProgress(unittest.TestCase):
    def test_market_date_formats(self):
        self.assertEqual(common.bar_market_date("20261124"), date(2026, 11, 24))
        self.assertEqual(common.bar_market_date("2026-11-24T05:00:00Z", "TSLA.US"), date(2026, 11, 24))
        self.assertEqual(common.bar_market_date(1795496400, "TSLA.US"), date(2026, 11, 24))
        self.assertIsNone(common.bar_market_date("", "TSLA.US"))

    def test_in_progress_only_during_regular_hours_of_bar_day(self):
        stamp = "2026-11-24T05:00:00Z"  # TSLA 日 K 的实盘时间戳形态(= 美东当日 00:00)
        self.assertTrue(common.is_bar_in_progress(stamp, "TSLA.US", now=et(11, 24, 9, 31)))
        self.assertTrue(common.is_bar_in_progress(stamp, "TSLA.US", now=et(11, 24, 15, 59)))
        self.assertFalse(common.is_bar_in_progress(stamp, "TSLA.US", now=et(11, 24, 16, 0)))
        self.assertFalse(common.is_bar_in_progress(stamp, "TSLA.US", now=et(11, 24, 21, 0)))   # 夜盘
        self.assertFalse(common.is_bar_in_progress(stamp, "TSLA.US", now=et(11, 25, 9, 31)))  # 次日盘前
        self.assertTrue(common.kline_last_bar_in_progress([{"time": stamp}], "TSLA.US", now=et(11, 24, 10, 0)))
        self.assertFalse(common.kline_last_bar_in_progress([{"close": "1"}], "TSLA.US", now=et(11, 24, 10, 0)))
        self.assertFalse(common.kline_last_bar_in_progress([], "TSLA.US", now=et(11, 24, 10, 0)))

    def test_hk_uses_its_own_close(self):
        stamp = "2026-11-24T01:30:00Z"  # 09:30 HKT
        self.assertTrue(common.is_bar_in_progress(stamp, "0700.HK", now=datetime(2026, 11, 24, 10, 0)))
        self.assertFalse(common.is_bar_in_progress(stamp, "0700.HK", now=datetime(2026, 11, 24, 16, 0)))


class TestIndicatorsIntradayVolume(unittest.TestCase):
    """09:31 的成交量约为全天的 4.5%:不能拿去算量比,也不能判「缩量」。"""

    CLOSES = [100 + 3 * math.sin(i / 7) + (i % 5) * 0.2 for i in range(120)]

    def _mocks(self, in_progress):
        bars = daily_bars(self.CLOSES, last_volume=45_000)
        stack = contextlib.ExitStack()
        stack.enter_context(unittest.mock.patch.object(
            calc_indicators, "get_kline_adjusted", lambda symbol, count=300, period="day": bars))
        stack.enter_context(unittest.mock.patch.object(
            calc_indicators, "kline_last_bar_in_progress",
            lambda bars, symbol="US", now=None: in_progress))
        return stack

    def test_partial_volume_is_not_a_volume_ratio(self):
        with self._mocks(True):
            ind = calc_indicators.compute_all("TSLA.US")
        self.assertTrue(ind["intraday_bar"])
        self.assertIsNone(ind["volume_ratio"])            # 修复前 ≈0.05 → 一律「缩量」
        self.assertEqual(ind["price"], self.CLOSES[-1])   # 价格仍是盘中实时值
        self.assertEqual(ind["bars"], len(self.CLOSES))
        self.assertIsNotNone(ind["obv"]["obv"])           # OBV 用已收盘的 K 线
        self.assertIsNotNone(ind["obv"]["slope_20"])
        self.assertIsNotNone(ind["mfi14"])

    def test_completed_bar_is_unchanged(self):
        with self._mocks(False):
            ind = calc_indicators.compute_all("TSLA.US")
        self.assertFalse(ind["intraday_bar"])
        self.assertLess(ind["volume_ratio"], 0.1)

    def test_text_output_flags_intraday_bar(self):
        with self._mocks(True):
            _, out = _capture(calc_indicators.show_indicators, "TSLA.US")
        self.assertIn("最后一根为当日未收盘 K 线", out)
        self.assertIn("N/A(当日未收盘)", out)
        self.assertIn("MFI(14),截至上根收盘", out)


class TestTechnicalScoreRenormalised(unittest.TestCase):
    """量比(5 分)盘中无法评估:总分按可得满分 95 折算,而不是白丢 5 分。"""

    @staticmethod
    def _ind(intraday):
        ind = {"symbol": "TSLA.US", "bars": 120, "price": 100.0, "ma": {}, "ema": {}, "macd": {},
               "rsi14": None, "kdj": {}, "bollinger": {}, "atr14": None, "atr_pct": None,
               "obv": {"obv": 1.0, "slope_20": 1.0, "rising_20": True},
               "mfi14": 50.0, "volume_ratio": 0.5, "roc20": None, "williams_r14": None,
               "cci20": None, "position_52w": {}, "donchian20": {}, "donchian20_prior": {},
               "max_drawdown": 0.1, "total_return_pct": 0.2, "signals": []}
        if intraday:
            ind["intraday_bar"] = True
            ind["volume_ratio"] = None
        return ind

    def _score(self, intraday):
        with unittest.mock.patch.object(calc_technical_score, "compute_all",
                                        lambda symbol, count=300: self._ind(intraday)):
            return _run(calc_technical_score.score, "TSLA.US", output_json=True)

    def test_intraday_score_is_scaled_to_available_points(self):
        r = self._score(True)  # OBV 上行 +10、MFI 健康区 +5;量比未计分
        self.assertEqual((r["raw_score"], r["score_basis"], r["technical_score"]), (15.0, 95, 15.8))
        self.assertTrue(r["intraday_bar"])
        self.assertIn("量比 当日未收盘,未计分 +0", r["dimensions"]["量能"]["detail"])

    def test_after_close_score_is_unchanged(self):
        r = self._score(False)
        self.assertEqual((r["raw_score"], r["score_basis"], r["technical_score"]), (15.0, 100, 15.0))
        self.assertFalse(r["intraday_bar"])

    def test_text_output_explains_scaling(self):
        with unittest.mock.patch.object(calc_technical_score, "compute_all",
                                        lambda symbol, count=300: self._ind(True)):
            _, out = _capture(calc_technical_score.score, "TSLA.US")
        self.assertIn("当日 K 线未收盘", out)
        self.assertIn("95 折算", out)


class TestEntryRulesIntradayVolume(_StashCase):
    """下跌后当日反弹、开盘一分钟的量:修复前 D4「缩量反弹」直接判不买。"""

    CLOSES = [100.0] * 70 + ramp(99.5, -0.008, 10) + [92.5]
    ARGS = SimpleNamespace(lookback=60, max_stop_pct=8.0, earnings_days=None, target_price=None,
                           now="2026-11-24 10:00", sector_top_decline=None, recent_stopout=None,
                           familiar=None, prepost_move=None, sector_breakout="no", no_heat=True,
                           smallcap_usd=2e9, sector=None, sector_chg_pct=1.0, output_json=True)

    def _analyze(self, *, in_progress, last_volume=45_000, now=None, quote=None, bars=None):
        bars = daily_bars(self.CLOSES, last_volume=last_volume) if bars is None else bars
        fakes = {
            "get_kline_adjusted": lambda symbol, count=260, period="day": bars,
            "kline_last_bar_in_progress": lambda b, symbol="US", now=None: in_progress,
            "_in_heat_rank": lambda s: None,
            "_is_small_cap": lambda s, t, price=None: None,
            "_closed_dates": lambda m: set(),
            "_days_to_earnings": lambda s, now=None: 30,
        }
        with contextlib.ExitStack() as stack:
            for name, fake in fakes.items():
                stack.enter_context(unittest.mock.patch.object(entry, name, fake))
            if quote is not None:
                real_now = common.market_now
                # 只把「此刻」定在给定时间;带明确时间参数的调用(K 线日期等)仍走原实现
                stack.enter_context(unittest.mock.patch.object(common, "run_cli", lambda *a, **k: quote))
                stack.enter_context(unittest.mock.patch.object(
                    common, "market_now",
                    lambda m, at=None, **kw: now if at is None else real_now(m, at)))
            return _run(entry.analyze, "TSLA.US", self.ARGS)

    def test_partial_volume_is_unknown_not_shrink(self):
        live = [{"symbol": "TSLA.US", "last": "92.50", "prev_close": "100.0"}]
        r = self._analyze(in_progress=True, quote=live, now=et(11, 24, 10, 0))
        self.assertTrue(r["intraday_bar"])
        d4 = r["rules"]["D4"]
        self.assertEqual(d4["status"], "manual")            # 修复前 triggered → ❌ 不买
        self.assertIn("当日未收盘", d4["evidence"])
        self.assertIn("未收盘", r["data_quality"]["volume"])
        self.assertTrue(any("未收盘 bar" in reason for reason in r["verdict_reasons"]))
        self.assertEqual((r["price"], r["price_source"]), (92.5, "quote"))
        self.assertIsNone(r["price_note"])

    def test_completed_low_volume_bar_still_counts(self):
        live = [{"symbol": "TSLA.US", "last": "92.50", "prev_close": "100.0"}]
        r = self._analyze(in_progress=False, quote=live, now=et(11, 24, 21, 0))
        self.assertFalse(r["intraday_bar"])
        self.assertEqual(r["rules"]["D4"]["status"], "triggered")
        self.assertNotIn("volume", r["data_quality"])

    def test_premarket_run_quotes_regular_price_and_says_so(self):
        """入场规则按日 K 判定:盘前运行时参考价取常规时段的 last,并说明盘前价未被采用。"""
        closes = self.CLOSES[:-1]  # 当天还没开盘,最后一根是昨日已收盘的 bar
        prior_close = closes[-1]
        quote = [{"symbol": "TSLA.US", "last": str(prior_close), "prev_close": "100.0",
                  "pre_market": {"last": "92.50", "timestamp": "2026-11-24T14:16:31Z"}}]
        r = self._analyze(in_progress=False, quote=quote, now=et(11, 24, 9, 20), bars=daily_bars(closes))
        self.assertEqual(r["price"], float(str(prior_close)))
        self.assertIn("延长时段最新价 92.5(盘前价 美东 09:16)", r["price_note"])
        self.assertEqual(r["underlying_price_info"]["source"], "pre_market")


# --------------------------------------------------------------------------- #
# 3. D12 半日市
# --------------------------------------------------------------------------- #

def _closed_entry(day, content, date_type, kind):
    """closed-calendar 的一个日期桶(2026-11-24 实盘形态,只保留逻辑用到的字段)。"""
    return {"date": day, "count": 0,
            "infos": [{"market": "US", "content": content, "date_type": date_type, "type": "closed",
                       "ext": {"holiday_date": day, "holiday_type": kind}}]}


US_CLOSED_CALENDAR = [
    _closed_entry("2026-11-26", "感恩节", "全日", "full_day"),
    _closed_entry("2026-11-27", "感恩节翌日", "半天", "half_day"),
    _closed_entry("2026-12-24", "平安夜", "半天", "half_day"),
    _closed_entry("2026-12-25", "圣诞节", "全日", "full_day"),
]


class TestHalfDayIsNotAHoliday(unittest.TestCase):
    def _closed_dates(self):
        with unittest.mock.patch.object(entry, "get_finance_calendar", lambda **k: US_CLOSED_CALENDAR):
            return entry._closed_dates("US")

    def test_only_full_day_closures_count(self):
        self.assertEqual(self._closed_dates(), {"2026-11-26", "2026-12-25"})

    def test_half_day_detection(self):
        self.assertTrue(entry._is_half_day({"date_type": "半天"}))
        self.assertTrue(entry._is_half_day({"ext": {"holiday_type": "Half_Day"}}))
        self.assertFalse(entry._is_half_day({"date_type": "全日", "ext": {"holiday_type": "full_day"}}))
        self.assertFalse(entry._is_half_day({}))

    def test_d12_still_applies_on_half_day_morning(self):
        closed = self._closed_dates()

        def d12(month, day, hour, minute):
            features = entry.build_features(daily_bars([100.0] * 60))
            opts = {"now": datetime(2026, month, day, hour, minute), "market": "US", "closed_dates": closed}
            return entry.check_rules(features, opts)["rules"]["D12"]

        self.assertEqual(d12(11, 27, 9, 15)["status"], "triggered")  # 修复前「为休市日」放行
        self.assertEqual(d12(11, 26, 9, 15)["status"], "clear")
        self.assertIn("休市日", d12(11, 26, 9, 15)["evidence"])
        self.assertEqual(d12(12, 25, 9, 15)["status"], "clear")


# --------------------------------------------------------------------------- #
# 4. 零成交腿
# --------------------------------------------------------------------------- #

AAPL_SPOT = 354.07
# AAPL 2026-12-04 实盘链的裁剪版(2026-11-24 09:3x ET 抓取):80 档里 16 档 last=0
AAPL_1204_ROWS = [
    {"strike": "317.5", "call_last": "0", "call_iv": "0.000", "put_last": "0.60", "put_iv": "0.362"},
    {"strike": "350", "call_last": "6.05", "call_iv": "0.254", "put_last": "6.47", "put_iv": "0.256"},
    {"strike": "360", "call_last": "2.10", "call_iv": "0.236", "put_last": "12.15", "put_iv": "0.221"},
    {"strike": "367.5", "call_last": "0.66", "call_iv": "0.221", "put_last": "0", "put_iv": "0.000"},
    {"strike": "420", "call_last": "0.01", "call_iv": "0.337", "put_last": "0", "put_iv": "0.000"},
]


class TestZeroLastLeg(_StashCase):
    def _leg(self, strike, action="BUY", **extra):
        leg = {"underlying": "AAPL.US", "expiry": "2026-12-04", "strike": strike,
               "type": "CALL", "action": action, "quantity": 1}
        leg.update(extra)
        return leg

    def _mocks(self, rows):
        stack = contextlib.ExitStack()
        chain = [dict(row, standard="true") for row in rows]
        stack.enter_context(unittest.mock.patch.object(calc_option_pnl, "get_option_chain", lambda u, e: chain))
        stack.enter_context(unittest.mock.patch.object(calc_option_pnl, "get_underlying_price", lambda s: AAPL_SPOT))
        stack.enter_context(unittest.mock.patch.object(calc_option_pnl, "days_to_years",
                                                      lambda expiry, today=None, **kw: 10 / 365))
        return stack

    def _with_modelled_iv(self):
        rows = [dict(row) for row in AAPL_1204_ROWS]
        rows[0]["call_iv"] = "0.410"  # 无成交但链上仍有 IV 的档位
        return rows

    def test_zero_last_without_price_or_iv_is_an_error(self):
        """修复前 317.5C 被当成 0 成本:最大盈利显示 4855.0(有限)。"""
        legs = [self._leg(317.5), self._leg(350, "SELL")]
        with self._mocks(AAPL_1204_ROWS), self.assertRaises(ValueError) as caught:
            _run(calc_option_pnl.analyze_pnl, legs, output_json=True)
        self.assertIn('"price"', str(caught.exception))

    def test_manual_price_is_used_and_flagged(self):
        """熊市价差: 买 420P(深度价内、当日无成交,按假设价 68)+ 卖 360P @12.15。"""
        legs = [self._leg(420, type="PUT", price=68.0), self._leg(360, "SELL", type="PUT")]
        with self._mocks(AAPL_1204_ROWS):
            r = _run(calc_option_pnl.analyze_pnl, legs, output_json=True)
        self.assertEqual([lc["price_source"] for lc in r["legs_detail"]], ["manual", "last"])
        self.assertEqual(r["estimated_legs"], 1)
        self.assertEqual(r["total_cost"], 5585.0)            # 6800 − 1215
        self.assertEqual(r["max_profit"], "415.0 (有限)")    # (420−360)×100 − 5585
        self.assertEqual(r["max_loss"], "-5585.0 (有限)")
        self.assertEqual(r["break_even_points"], [364.15])   # 420 − 55.85

    def test_bs_estimate_from_chain_iv(self):
        legs = [self._leg(317.5), self._leg(350, "SELL")]
        with self._mocks(self._with_modelled_iv()):
            r = _run(calc_option_pnl.analyze_pnl, legs, output_json=True)
        (leg,) = [lc for lc in r["legs_detail"] if lc["price_source"] == "bs_from_iv"]
        self.assertEqual(leg["last"], common.bs_price(AAPL_SPOT, 317.5, 10 / 365, 0.045, 0.410, "C"))
        self.assertTrue(36.5 < leg["last"] < 38.5, leg["last"])  # 深度价内:内在价值 36.57 + 少量时间价值
        self.assertEqual(r["estimated_legs"], 1)

    def test_rate_reaches_the_estimate(self):
        legs = [self._leg(317.5), self._leg(350, "SELL")]
        with self._mocks(self._with_modelled_iv()):
            low = _run(calc_option_pnl.analyze_pnl, legs, output_json=True, rate=0.02)["legs_detail"][0]["last"]
            high = _run(calc_option_pnl.analyze_pnl, legs, output_json=True, rate=0.10)["legs_detail"][0]["last"]
        self.assertLess(low, high)

    def test_traded_legs_are_unchanged(self):
        with self._mocks(AAPL_1204_ROWS):
            r = _run(calc_option_pnl.analyze_pnl, [self._leg(350), self._leg(360, "SELL")], output_json=True)
        self.assertEqual(r["estimated_legs"], 0)
        self.assertEqual(r["total_cost"], 395.0)
        self.assertEqual(r["max_profit"], "605.0 (有限)")
        self.assertEqual(r["max_loss"], "-395.0 (有限)")
        self.assertEqual(r["break_even_points"], [353.95])

    def test_strike_missing_from_chain_is_reported(self):
        legs = [self._leg(312.5), self._leg(350, "SELL")]
        with self._mocks(AAPL_1204_ROWS), self.assertRaises(ValueError) as caught:
            _run(calc_option_pnl.analyze_pnl, legs, output_json=True)
        self.assertIn("没有 312.5 CALL 这一档", str(caught.exception))

    def test_text_output_flags_estimated_legs(self):
        legs = [self._leg(420, type="PUT", price=68.0), self._leg(360, "SELL", type="PUT")]
        with self._mocks(AAPL_1204_ROWS):
            _, out = _capture(calc_option_pnl.analyze_pnl, legs)
        self.assertIn("⚠️ 1 腿无当日成交价", out)
        self.assertIn("420.0 PUT(手动指定价)", out)
        self.assertIn("价=68.0", out)


# --------------------------------------------------------------------------- #
# 5. 美股沽空占比
# --------------------------------------------------------------------------- #

# JNJ 的 FINRA 每日空头成交(2026-11-24 抓取): 各股有自己的常态水平,单日 17.9%~60.9%
JNJ_SHORT_VOLUME = [
    ("2026-11-09", 0.552, 76429, 138383, "280.71"),
    ("2026-11-11", 0.405, 52405, 129442, "279.018"),
    ("2026-11-13", 0.609, 81621, 133997, "284.332"),
    ("2026-11-17", 0.267, 51185, 191618, "277.317"),
    ("2026-11-18", 0.440, 78786, 178851, "271.347"),
    ("2026-11-19", 0.179, 76342, 426390, "265.814"),
    ("2026-11-23", 0.532, 141256, 265403, "268.71"),
    ("2026-11-24", 0.494, 68180, 137956, "276.46"),
]
_US_DAY0 = 1794182400  # 2026-11-09T00:00:00Z


def jnj_rows():
    rows = []
    for day, rate, short_volume, total_volume, close in JNJ_SHORT_VOLUME:
        offset = (date.fromisoformat(day) - date(2026, 11, 9)).days
        rows.append({"timestamp": str(_US_DAY0 + offset * 86400), "rate": str(rate),
                     "nus_amount": str(short_volume), "ny_amount": "0",
                     "total_amount": str(total_volume), "close": close})
    return rows


class TestUsShortVolumeRatio(unittest.TestCase):
    def test_us_label_has_no_hk_thresholds(self):
        self.assertEqual(get_short_sale._rate_label(0.53, "US"), "53.0%")  # 修复前「53.0% 🔴(做空极活跃)」
        self.assertEqual(get_short_sale._rate_label(0.53, "US", 0.0), "53.0%")
        self.assertIn("做空极活跃", get_short_sale._rate_label(0.53, "HK"))
        self.assertIn("做空较活跃", get_short_sale._rate_label(0.30, "HK"))
        self.assertIn("做空清淡", get_short_sale._rate_label(0.05, "HK"))
        self.assertIn("做空极活跃", get_short_sale._rate_label(0.53))  # 未指明市场:保持原分档
        self.assertEqual(get_short_sale._rate_label(None, "US"), "")

    def test_us_label_compares_with_own_prior_mean(self):
        self.assertEqual(get_short_sale._rate_label(0.53, "US", 0.40), "53.0%(高于此前均值 40.0%)")
        self.assertEqual(get_short_sale._rate_label(0.53, "US", 0.45), "53.0%(接近此前均值 45.0%)")
        self.assertEqual(get_short_sale._rate_label(0.267, "US", 0.522), "26.7%(低于此前均值 52.2%)")

    def _fetch(self, market, rows, output_json=True):
        data = {"symbol": "X.US", "market": market, "data": rows}
        with unittest.mock.patch.object(get_short_sale, "get_short_trades", lambda s, count=20: data):
            return _capture(get_short_sale.fetch_short_sale, "X.US", output_json=output_json)

    def test_us_rows_and_basis(self):
        result, _ = self._fetch("US", jnj_rows())
        labels = [row["rate_label"] for row in result["data"]]
        self.assertEqual(labels[:3], ["55.2%", "40.5%", "60.9%"])  # 此前不足 3 天:只报数值
        self.assertEqual(labels[3], "26.7%(低于此前均值 52.2%)")
        self.assertEqual(labels[7], "49.4%(接近此前均值 42.6%)")
        self.assertNotIn("做空", " ".join(labels))
        self.assertEqual(result["data"][7]["prior_mean_rate"], 0.4263)
        self.assertIsNone(result["data"][2]["prior_mean_rate"])
        self.assertIn("FINRA", result["ratio_basis"])
        self.assertIn("--position", result["ratio_basis"])
        self.assertIn("空头成交占比", result["trend"])

    def test_us_text_output(self):
        _, out = self._fetch("US", jnj_rows(), output_json=False)
        self.assertIn("日空头成交量(FINRA)", out)
        self.assertIn("最新空头成交占比: 49.4%(接近此前均值 42.6%)", out)
        self.assertNotIn("做空极活跃", out)
        self.assertIn("不代表看空情绪", out)

    def test_hk_rows_unchanged(self):
        rows = [{"timestamp": str(_US_DAY0 + i * 86400), "rate": "0.531", "amount": "1000",
                 "total_amount": "1883", "balance": "500", "close": "341.6"} for i in range(3)]
        result, _ = self._fetch("HK", rows)
        self.assertEqual(result["data"][-1]["rate_label"], "53.1% 🔴(做空极活跃)")
        self.assertIn("HKEX", result["ratio_basis"])
        self.assertNotIn("prior_mean_rate", result["data"][-1])


class TestDashboardShortRatio(unittest.TestCase):
    def setUp(self):
        self._orig = (analyze_buy_sell.get_capital_flow_snapshot, analyze_buy_sell.get_short_trades)

    def tearDown(self):
        (analyze_buy_sell.get_capital_flow_snapshot,
         analyze_buy_sell.get_short_trades) = self._orig

    def _capital(self, market, rates, funds):
        analyze_buy_sell.get_capital_flow_snapshot = lambda s: funds
        analyze_buy_sell.get_short_trades = lambda s, count=10: {
            "market": market,
            "data": [{"timestamp": 1700000000 + i * 86400, "rate": r} for i, r in enumerate(rates)]}
        bulls, bears = [], []
        return analyze_buy_sell._dim_capital(f"X.{market}", bulls, bears), bulls, bears

    def test_us_ratio_is_shown_but_never_scored(self):
        (score, detail), bulls, bears = self._capital("US", [0.45, 0.5, 0.48, 0.53, 0.51], funds={})
        self.assertIsNone(score)  # 修复前: 凭 51% 的占比给出 40 分
        self.assertIn("空头成交占比 51%(FINRA,含做市对冲,不计分,此前均值 49%)", detail)
        self.assertEqual((bulls, bears), ([], []))  # 修复前 bear 因素: 沽空: 最新沽空成交占比 51%

        balanced = {"net": {"large": 0}, "capital_in": {"large": 100}, "capital_out": {"large": 100}}
        (score, detail), bulls, bears = self._capital("US", [0.53], funds=balanced)
        self.assertEqual(score, 50.0)  # 修复前 40
        self.assertIn("不计分", detail)
        self.assertEqual((bulls, bears), ([], []))

    def test_us_market_is_inferred_from_symbol_when_data_omits_it(self):
        orig = analyze_buy_sell.get_short_trades
        try:
            analyze_buy_sell.get_capital_flow_snapshot = lambda s: {}
            analyze_buy_sell.get_short_trades = lambda s, count=10: {"data": [{"rate": "0.53"}]}
            score, detail = analyze_buy_sell._dim_capital("X.US", [], [])
        finally:
            analyze_buy_sell.get_short_trades = orig
        self.assertIsNone(score)
        self.assertIn("不计分", detail)

    def test_hk_thresholds_unchanged(self):
        (score, detail), bulls, bears = self._capital("HK", [0.53], funds={})
        self.assertEqual(score, 40.0)
        self.assertEqual(bears, ["沽空: 最新沽空成交占比 53%"])
        (score, _), _, _ = self._capital("HK", [0.05], funds={})
        self.assertEqual(score, 55.0)
        (score, _), bulls, bears = self._capital("HK", [0.19], funds={})
        self.assertEqual(score, 50.0)
        self.assertEqual((bulls, bears), ([], []))

    def test_latest_row_is_the_newest_by_timestamp(self):
        rows = [{"timestamp": "1700005400", "rate": "0.20"}, {"timestamp": "1700000000", "rate": "0.55"}]
        analyze_buy_sell.get_capital_flow_snapshot = lambda s: {}
        analyze_buy_sell.get_short_trades = lambda s, count=10: {"market": "HK", "data": rows}
        bulls, bears = [], []
        score, detail = analyze_buy_sell._dim_capital("X.HK", bulls, bears)
        self.assertIn("沽空率 20%", detail)
        self.assertEqual((score, bears), (50.0, []))


# --------------------------------------------------------------------------- #
# 6. 美股盘口只有 1 档
# --------------------------------------------------------------------------- #

def _levels(start, count, side, volume=100):
    """从 start 起,买档往下 / 卖档往上各 count 档,每档 volume 股。"""
    step = -0.01 if side == "bids" else 0.01
    return [{"position": i + 1, "price": f"{start + step * i:.2f}", "volume": volume}
            for i in range(count)]


class TestOrderbookDepthLevels(unittest.TestCase):
    def _analyze(self, bids, asks, symbol="AAPL.US", output_json=True):
        with unittest.mock.patch.object(orderbook, "get_depth", lambda s: {"bids": bids, "asks": asks}):
            return _capture(orderbook.analyze, symbol, output_json=output_json)

    def test_top_of_book_only_has_no_verdict(self):
        """审计复现: 买一 2 股对卖一 37 股 → 修复前「🔴 卖盘显著占优(上方压制重)」。"""
        r, _ = self._analyze([{"position": 1, "price": "353.04", "volume": 2}],
                             [{"position": 1, "price": "353.37", "volume": 37}])
        self.assertEqual(r["verdict"], "⚪ 报价档位不足(1 档),无法判断盘口压力")
        self.assertEqual((r["depth_levels"], r["depth_sufficient"], r["min_depth_levels"]),
                         (1, False, 5))
        self.assertIsNone(r["bid_wall"])       # 修复前「最大买单墙」恒等于买一
        self.assertIsNone(r["ask_wall"])
        self.assertIsNone(r["volume_weighted_center"])
        self.assertEqual(r["spread"], 0.33)    # 价差只看买卖一,照常给出
        self.assertEqual((r["total_bid_volume"], r["total_ask_volume"]), (2.0, 37.0))
        self.assertEqual(r["imbalance"], -0.897)
        self.assertIn("LV1", r["note"])

    def test_five_levels_on_both_sides_are_enough(self):
        r, _ = self._analyze(_levels(353.04, 5, "bids", volume=300), _levels(353.37, 5, "asks"))
        self.assertEqual((r["depth_levels"], r["depth_sufficient"]), (5, True))
        self.assertEqual((r["bid_wall"]["price"], r["ask_wall"]["price"]), ("353.04", "353.37"))
        self.assertAlmostEqual(r["volume_weighted_center"], 353.1125, places=2)
        self.assertEqual(r["verdict"], "🟢 买盘显著占优(下方承接厚)")

    def test_one_thin_side_is_not_enough(self):
        r, _ = self._analyze(_levels(353.04, 4, "bids"), _levels(353.37, 10, "asks"))
        self.assertEqual((r["depth_levels"], r["depth_sufficient"]), (4, False))
        self.assertEqual(r["verdict"], "⚪ 报价档位不足(4 档),无法判断盘口压力")

    def test_hk_book_is_unchanged(self):
        r, _ = self._analyze(_levels(344.0, 10, "bids", volume=5000),
                             _levels(344.2, 10, "asks", volume=5000), symbol="0700.HK")
        self.assertEqual(r["verdict"], "⚪ 买卖盘均衡")
        self.assertEqual(r["volume_weighted_center"], 344.1)  # 两侧等量:买卖十档的挂量加权中枢
        self.assertEqual((r["bid_wall"]["price"], r["ask_wall"]["price"]), ("344.00", "344.20"))
        self.assertNotIn("LV1", r["note"])

    def test_text_output_explains_insufficient_depth(self):
        _, out = self._analyze([{"position": 1, "price": "353.04", "volume": 2}],
                               [{"position": 1, "price": "353.37", "volume": 37}], output_json=False)
        self.assertIn("可见档位不足: 买 1 档 / 卖 1 档,判断至少需 5 档", out)
        self.assertIn("(美股默认行情仅买一/卖一)", out)
        self.assertIn("仅可见档位", out)
        self.assertNotIn("最大买单墙", out)
        self.assertNotIn("挂量加权中枢", out)


if __name__ == "__main__":
    unittest.main()
