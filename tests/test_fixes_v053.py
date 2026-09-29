"""v0.5.3 修复回归(第三轮外部审查核实后修复的项)。

覆盖: 组合Greeks×100、OHLC同位过滤、美东夏令时纯算法、到期日 T≤0 行权概率、
B2 真回踩语义(引擎侧已在前文件覆盖)、涡轮到期日排序、负PE不参与估值排名、
仪表盘财报取最近一次。

运行: python -m unittest tests.test_fixes_v053 -v
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "decision", "technical", "quote", "fundamental", "market"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))

import calc_option_greeks as cog  # noqa: E402
import calc_indicators as ci  # noqa: E402
import calc_exercise_prob as cep  # noqa: E402
import check_entry_rules as cer  # noqa: E402
import compare_stocks as cs  # noqa: E402
import analyze_buy_sell as dash  # noqa: E402
import get_warrant as gw  # noqa: E402


class TestPortfolioGreeksMultiplier(unittest.TestCase):
    """期权腿 Greeks 必须乘合约乘数 100(与正股腿口径一致)。"""

    def test_option_leg_x100(self):
        orig = cog.get_quote
        try:
            cog.get_quote = lambda *a, **k: {
                "greeks": {"delta": 0.5, "gamma": 0.02, "theta": -0.1,
                           "vega": 0.08, "rho": 0.01},
                "iv_pct": 30.0}
            legs = [
                {"underlying": "X.US", "type": "STOCK", "action": "BUY", "quantity": 1,
                 "expiry": "", "strike": 0},
                {"underlying": "X.US", "type": "CALL", "action": "BUY", "quantity": 1,
                 "expiry": "2027-01-15", "strike": 100},
            ]
            r = cog.calc_portfolio_greeks(legs)
            # 正股 100×1 + 期权 0.5×1×100 = 150
            self.assertAlmostEqual(r["portfolio_greeks"]["delta"], 150.0, places=3)
            self.assertAlmostEqual(r["portfolio_greeks"]["gamma"], 0.02 * 100, places=3)
        finally:
            cog.get_quote = orig


class TestAlignedKlineFiltering(unittest.TestCase):
    """OHLCV 同位过滤: 任一字段缺失整根剔除,四列严格对齐。"""

    def test_scattered_none_aligned(self):
        bars = []
        for i in range(40):
            bar = {"open": 100 + i, "close": 100.5 + i, "high": 101 + i,
                   "low": 99.5 + i, "volume": 1000 + i}
            if i in (5, 17, 30):
                bar["volume"] = None      # 只缺 volume
            if i == 22:
                bar["close"] = None       # 只缺 close
            bars.append(bar)
        orig = ci.get_kline_adjusted
        try:
            ci.get_kline_adjusted = lambda symbol, count=300: bars
            ind = ci.compute_all("TEST.US", count=40)
            self.assertEqual(ind["bars"], 36)  # 40 - 4 根含 None
            self.assertIsNotNone(ind["rsi14"])
            self.assertIsInstance(ind["signals"], list)
        finally:
            ci.get_kline_adjusted = orig


class TestEtDstAlgorithm(unittest.TestCase):
    """美东偏移纯算法: 夏令时 3月第2个周日 ~ 11月第1个周日。"""

    def test_known_dates(self):
        cases = [
            (datetime(2026, 1, 15, 12), -5),
            (datetime(2026, 3, 7, 12), -5),    # 第2个周日(3/8)前一天
            (datetime(2026, 3, 8, 12), -4),    # 进入夏令时
            (datetime(2026, 7, 4, 12), -4),
            (datetime(2026, 10, 31, 12), -4),  # 11月第1个周日(11/1,周日)前一天
            (datetime(2026, 11, 1, 12), -5),   # 当天凌晨2点已结束夏令时
            (datetime(2026, 11, 2, 12), -5),
        ]
        for d, want in cases:
            with self.subTest(d=d.date()):
                self.assertEqual(cer._et_utc_offset(d), want)


class TestExerciseProbExpiryDay(unittest.TestCase):
    """到期日当天 T=0 不能进 BS 公式(σ√T=0 除零)。"""

    def setUp(self):
        self._px = cep.get_underlying_price
        self._chain = cep.get_option_chain

    def tearDown(self):
        cep.get_underlying_price = self._px
        cep.get_option_chain = self._chain

    def _run(self, strike, cp):
        cep.get_underlying_price = lambda s: 100.0
        cep.get_option_chain = lambda u, e: [{"strike": str(strike), "put_iv": "0.3",
                                              "call_iv": "0.3"}]
        return cep.exercise_prob("X.US", "2020-01-01", strike, cp, output_json=False)

    def test_expired_no_crash(self):
        r = self._run(110.0, "PUT")   # 价内 put → 100%
        self.assertEqual(r["exercise_prob_bs"], 100.0)
        r2 = self._run(110.0, "CALL")  # 价外 call(现价100<行权110) → 0%
        self.assertEqual(r2["exercise_prob_bs"], 0.0)
        self.assertIn("过期", r["method_note"])


class TestWarrantExpirySort(unittest.TestCase):
    """到期日排序用日期序,不再 to_float 归零失效。"""

    def test_expiry_sort_by_date(self):
        orig = gw.get_warrant_list
        try:
            gw.get_warrant_list = lambda s: [
                {"symbol": "a.HK", "name": "A", "expiry": "2028-01-01",
                 "last": "1", "leverage_ratio": "3", "type": "Call"},
                {"symbol": "b.HK", "name": "B", "expiry": "2026-03-01",
                 "last": "1", "leverage_ratio": "2", "type": "Call"},
                {"symbol": "c.HK", "name": "C", "expiry": "2027-06-01",
                 "last": "1", "leverage_ratio": "5", "type": "Call"},
            ]
            r = gw._list_mode("700.HK", sort="expiry", count=10, enrich=0,
                              direction=None, output_json=True)
            exps = [w["到期日"] for w in r["warrants"]]
            self.assertEqual(exps, sorted(exps))
            self.assertEqual(exps[0], "2026-03-01")
        finally:
            gw.get_warrant_list = orig


class TestCompareNegativePE(unittest.TestCase):
    """负 PE(亏损)不参与「谁最便宜」排名与最优标记。"""

    def test_negative_pe_excluded(self):
        orig = cs.compare_stocks_cli
        try:
            cs.compare_stocks_cli = lambda symbols, currency="USD": [
                {"counter_id": "ST/US/LOSS", "pe": "-5.2", "pb": "0.8",
                 "ps": "1.2", "roe": "-20", "roa": "-5", "net_margin": "-15",
                 "div_yld": "0"},
                {"counter_id": "ST/US/PROF", "pe": "22.4", "pb": "3.1",
                 "ps": "4.0", "roe": "18", "roa": "9", "net_margin": "25",
                 "div_yld": "1.2"},
            ]
            r = cs.fetch_compare(["LOSS.US", "PROF.US"])
            self.assertEqual(r["best_per_metric"]["PE"], "PROF.US")
            # 负 PE 不参与 PE 维度排名(无该维度条目)
            self.assertIsNone(r["ranks"]["LOSS.US"].get("pe"))
            self.assertEqual(r["ranks"]["PROF.US"]["pe"], 1)
        finally:
            cs.compare_stocks_cli = orig


class TestEarningsNearest(unittest.TestCase):
    """仪表盘事件维取「最近一次」未来财报,日历乱序不再取错。"""

    def test_unordered_takes_nearest(self):
        orig = dash.get_finance_calendar
        try:
            base = datetime.now()
            today = base.strftime("%Y.%m.%d")
            month_later_m = base.month % 12 + 1
            month_later_y = base.year + (1 if base.month == 12 else 0)
            near_d = f"{month_later_y}.{month_later_m:02d}.15"   # ~1 个月后
            far_d = f"{base.year + 1}.06.15"                     # 明年
            # 乱序: 远期在前,近期在后
            dash.get_finance_calendar = lambda **k: [
                {"date": "a", "infos": [{"date": far_d, "content": "远期"}]},
                {"date": "b", "infos": [{"date": today, "content": "今天(最近)"}]},
                {"date": "c", "infos": [{"date": near_d, "content": "一个月后"}]},
            ]
            bulls, bears = [], []
            score, note = dash._dim_event("X.US", bulls, bears)
            self.assertIn("天后财报", note)
            self.assertIn("0 天后财报", note)  # 取到今天,而不是远期
            self.assertTrue(any("波动风险" in b for b in bears))  # ≤7 天进空头
        finally:
            dash.get_finance_calendar = orig


if __name__ == "__main__":
    unittest.main()
