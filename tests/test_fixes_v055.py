"""v0.5.5 修复回归(第五轮外部审查核实后修复的项)。

覆盖: 股息 TTM 12 个月窗口、IPO 上市日按市场时区解析、原生 Greeks 部分
缺失打印兜底、ATM 行权价按现价最近、GEX IV 回退按 call/put 同侧、
daily_returns 长度契约、盘口中枢分子分母同口径、市场温度 0 度判偏冷、
VWAP 趋势不被开盘值绑架、BS 脏输入防护。

运行: python -m unittest tests.test_fixes_v055 -v
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from datetime import date, datetime, timezone

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "calendar", "quote", "fundamental", "technical",
             "intraday", "sentiment", "decision"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))

import common  # noqa: E402
import get_dividend_quality as gdq  # noqa: E402
import get_ipo_listings as gip  # noqa: E402
import get_option_quote as goq  # noqa: E402
import get_iv_history as gih  # noqa: E402
import calc_gex as cgex  # noqa: E402
import indicators as ind  # noqa: E402
import get_orderbook_pressure as gob  # noqa: E402
import get_vwap_analysis as gva  # noqa: E402
import daily_briefing as dbf  # noqa: E402


class TestDividendTtmWindow(unittest.TestCase):
    """TTM 窗口必须恰好 12 个月:前一年取同月之后(严格大于),不含去年同月。"""

    def _run(self, divs, price=100.0):
        orig_h, orig_p = gdq.get_dividend_history, gdq.get_underlying_price
        try:
            gdq.get_dividend_history = lambda s: divs
            gdq.get_underlying_price = lambda s: price
            return gdq.analyze("X.US", quiet=True)
        finally:
            gdq.get_dividend_history, gdq.get_underlying_price = orig_h, orig_p

    def test_quarterly_exactly_4_payments(self):
        # 季付(2/5/8/11 月),数据截至 2026.08:窗口 2025-09 ~ 2026-08
        # 应只含 2025.11 + 2026.02/05/08 共 4 期(旧代码把 2025.08 也算进 → 5 期)
        divs = [{"ex_date": f"{y}.{m:02d}.10", "amount": 0.25, "currency": "USD"}
                for y in (2025, 2026) for m in (2, 5, 8, 11)
                if not (y == 2026 and m == 11)]
        r = self._run(divs)
        self.assertAlmostEqual(r["ttm_dividend_per_share"], 1.0, places=6)
        self.assertAlmostEqual(r["ttm_yield_pct"], 1.0, places=6)

    def test_annual_not_doubled(self):
        # 年付 8 月派:窗口内只应有今年一期(旧代码两年都算 → 翻倍)
        divs = [{"ex_date": "2025.08.10", "amount": 0.4, "currency": "USD"},
                {"ex_date": "2026.08.10", "amount": 0.4, "currency": "USD"}]
        r = self._run(divs)
        self.assertAlmostEqual(r["ttm_dividend_per_share"], 0.4, places=6)


class TestIpoMarketTimezone(unittest.TestCase):
    """上市日时间戳是当地午夜,按 UTC 解析会提前一天。"""

    # 实测 6802.HK:香港 2026-09-30 00:00 = UTC 2026-09-29 16:00
    _HK_STAMP = 1790697600
    # 美东午夜:NY 2026-09-30 00:00 EDT = UTC 04:00
    _NY_STAMP = 1790740800

    def test_hk_stamp_parses_hk_date(self):
        self.assertEqual(
            datetime.fromtimestamp(self._HK_STAMP, tz=gip._market_tz("hk")).date(),
            date(2026, 9, 30))
        # 旧口径(UTC)确实提前一天 —— 回归锚点
        self.assertEqual(
            datetime.fromtimestamp(self._HK_STAMP, tz=timezone.utc).date(),
            date(2026, 9, 29))

    def test_us_stamp_parses_ny_date(self):
        for tz in (gip._market_tz("us"), gip._EtRuleTz()):
            with self.subTest(tz=tz):
                self.assertEqual(
                    datetime.fromtimestamp(self._NY_STAMP, tz=tz).date(),
                    date(2026, 9, 30))

    def test_unknown_market_defaults_utc(self):
        self.assertIs(gip._market_tz("jp"), timezone.utc)

    def test_days_until_uses_passed_tz(self):
        # 两侧行为不依赖测试运行日期:仅验证带 tz 调用可正常出值
        self.assertIsInstance(gip._days_until(self._HK_STAMP, gip._market_tz("hk")), str)
        self.assertEqual(gip._days_until(None, gip._market_tz("hk")), "")


class TestNativeGreeksPartialPrint(unittest.TestCase):
    """原生接口返回 delta 但缺 gamma 等字段时,打印路径不能 TypeError。"""

    def test_partial_greeks_print(self):
        orig = (goq.run_cli, goq.get_option_chain, goq.get_underlying_price,
                goq.get_option_contract_metrics)
        try:
            goq.run_cli = lambda *a, **k: None
            goq.get_option_chain = lambda u, e: []
            goq.get_underlying_price = lambda u: 100.0
            goq.get_option_contract_metrics = lambda syms: {
                syms[0]: {"delta": 0.5, "oi": 10}}  # 有 delta,无 gamma/theta/vega/rho
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = goq.get_quote("X.US", "2027-01-15", 100.0, "CALL")
            self.assertEqual(r["greeks_source"], "native")
            self.assertEqual(r["greeks"]["gamma"], 0.0)
            self.assertIn("gamma = 0.0000", buf.getvalue())
        finally:
            (goq.run_cli, goq.get_option_chain, goq.get_underlying_price,
             goq.get_option_contract_metrics) = orig


class TestAtmIvNearestStrike(unittest.TestCase):
    """ATM = 离现价最近且有有效 IV 的行权价,不再被深度 OTM 的巨量成交绑架。"""

    _CHAIN = [
        {"strike": "50", "call_vol": "999999", "put_vol": "999999",
         "call_iv": "0.50", "put_iv": "0.50"},
        {"strike": "100", "call_vol": "10", "put_vol": "10",
         "call_iv": "0.30", "put_iv": "0.28"},
        {"strike": "150", "call_vol": "0", "put_vol": "0",
         "call_iv": "0.60", "put_iv": "0.60"},
    ]

    def test_nearest_with_iv(self):
        orig = (gih.get_option_expirations, gih.get_option_chain,
                gih.get_underlying_price)
        try:
            gih.get_option_expirations = lambda s: ["2027-01-15"]
            gih.get_option_chain = lambda s, e: self._CHAIN
            gih.get_underlying_price = lambda s: 101.0
            iv, meta = gih.get_current_atm_iv("X.US")
            self.assertEqual(meta["strike"], 100.0)
            self.assertAlmostEqual(iv, (0.30 + 0.28) / 2, places=6)
        finally:
            (gih.get_option_expirations, gih.get_option_chain,
             gih.get_underlying_price) = orig

    def test_no_price_falls_back_to_volume(self):
        orig = (gih.get_option_expirations, gih.get_option_chain,
                gih.get_underlying_price)
        try:
            gih.get_option_expirations = lambda s: ["2027-01-15"]
            gih.get_option_chain = lambda s, e: self._CHAIN
            gih.get_underlying_price = lambda s: None
            iv, meta = gih.get_current_atm_iv("X.US")
            self.assertEqual(meta["strike"], 50.0)  # 回退旧的流动性最好口径
        finally:
            (gih.get_option_expirations, gih.get_option_chain,
             gih.get_underlying_price) = orig


class TestGexIvFallbackBySide(unittest.TestCase):
    """put 侧原生 gamma 与 put_iv 同时缺失时,回退只能用 put 侧 IV(旧代码
    硬编码 call_iv,偏斜下失真;chain 无 put_iv 时应得 0 而非借用 call IV)。"""

    def test_put_side_never_borrows_call_iv(self):
        orig = (cgex.get_underlying_price, cgex.get_option_chain, cgex.get_chain_oi)
        try:
            cgex.get_underlying_price = lambda s: 100.0
            cgex.get_option_chain = lambda u, e: [{"strike": "100", "call_iv": "0.30"}]
            cgex.get_chain_oi = lambda s, e: {
                "oi_mode": True,
                "strikes": {100.0: {"call_oi": 10, "put_oi": 10,
                                    "call_gamma": None, "put_gamma": None,
                                    "call_iv": 0.30, "put_iv": None}}}
            r = cgex.calc_gex("X.US", "2027-06-18", output_json=True)
            row = r["per_strike"][0]
            self.assertGreater(row["call_gamma"], 0.0)   # call 侧用 call_iv
            self.assertEqual(row["put_gamma"], 0.0)      # put 侧不得借用 call_iv
            self.assertEqual(r["weight_mode"], "oi")
        finally:
            (cgex.get_underlying_price, cgex.get_option_chain,
             cgex.get_chain_oi) = orig


class TestDailyReturnsContract(unittest.TestCase):
    """输出必须比输入恰少一个元素(0/None 按 0 收益占位),下游按位对齐才不错位。"""

    def test_zero_and_none_keep_length(self):
        self.assertEqual(len(ind.daily_returns([100.0, 0.0, 101.0, 102.0])), 3)
        self.assertEqual(ind.daily_returns([100.0, 0.0, 101.0, 102.0])[1], 0.0)
        self.assertEqual(len(ind.daily_returns([100.0, None, 102.0])), 2)
        # 正常序列不受影响
        self.assertAlmostEqual(ind.daily_returns([100.0, 110.0])[0], 0.1, places=9)


class TestOrderbookCenterSameBasis(unittest.TestCase):
    """挂量加权中枢:分子分母同口径,价格缺失的档位不进分母。"""

    def test_invalid_price_level_excluded_from_denominator(self):
        orig = gob.get_depth
        try:
            gob.get_depth = lambda s: {
                "bids": [{"position": 1, "price": "", "volume": 100},
                         {"position": 2, "price": "99", "volume": 100}],
                "asks": [{"position": 1, "price": "101", "volume": 100}],
            }
            r = gob.analyze("X.US", output_json=True)
            # (99×100 + 101×100) / 200 = 100.0;旧分母含无效档 → 66.667
            self.assertAlmostEqual(r["volume_weighted_center"], 100.0, places=6)
        finally:
            gob.get_depth = orig


class TestTempEmoji(unittest.TestCase):
    """温度 0 度是最冷端,必须判偏冷(真值判断会把 0 吞进「温和」)。"""

    def test_boundaries(self):
        self.assertEqual(dbf._temp_emoji(0), "❄️偏冷")
        self.assertEqual(dbf._temp_emoji(30), "❄️偏冷")
        self.assertEqual(dbf._temp_emoji(39.9), "❄️偏冷")
        self.assertEqual(dbf._temp_emoji(40), "🌡️温和")
        self.assertEqual(dbf._temp_emoji(50), "🌡️温和")
        self.assertEqual(dbf._temp_emoji(None), "🌡️温和")
        self.assertEqual(dbf._temp_emoji(60), "🔥偏热")
        self.assertEqual(dbf._temp_emoji(70), "🔥偏热")


class TestVwapTrendIndependentOfOpen(unittest.TestCase):
    """30 分钟 VWAP 趋势只取决于 30 分钟前值,开盘首档 avg_price 缺失不应绑架。"""

    def test_missing_open_avg_still_computes_trend(self):
        orig = gva.get_intraday
        try:
            rows = [{"price": f"{100 + i * 0.01:.2f}", "avg_price": "100.00"}
                    for i in range(70)]
            rows[0]["avg_price"] = ""          # 开盘档缺失(旧代码会因此不给趋势)
            rows[-30]["avg_price"] = "99.00"   # 30 分钟前明显更低 → 上行
            gva.get_intraday = lambda s, date=None: rows
            r = gva.analyze("X.US", output_json=True)
            self.assertEqual(r["vwap_trend_30m"], "上行")
        finally:
            gva.get_intraday = orig


class TestBsDirtyInputGuards(unittest.TestCase):
    """S/K ≤ 0 的脏输入返回退化值,不进 log/除零崩溃。"""

    def test_greeks_all_zero(self):
        for s, k in ((0, 100), (100, 0), (-5, 100), (100, -1)):
            g = common.bs_greeks(s, k, 1.0, 0.05, 0.3, "C")
            self.assertEqual(g, {"delta": 0.0, "gamma": 0.0, "theta": 0.0,
                                 "vega": 0.0, "rho": 0.0}, f"S={s},K={k}")

    def test_price_zero(self):
        self.assertEqual(common.bs_price(0, 100, 1.0, 0.05, 0.3, "C"), 0.0)
        self.assertEqual(common.bs_price(100, 0, 1.0, 0.05, 0.3, "P"), 0.0)

    def test_normal_inputs_unchanged(self):
        g = common.bs_greeks(100, 100, 1.0, 0.05, 0.3, "C")
        self.assertGreater(g["gamma"], 0.0)
        self.assertGreater(common.bs_price(100, 90, 1.0, 0.05, 0.3, "C"), 10.0)


if __name__ == "__main__":
    unittest.main()
