"""v0.5.0 入场纪律检查器(check_entry_rules)的规则引擎测试。

用合成 K 线逐条验证: 不买规则触发/不触发、买点结构匹配、
盈亏比闸门、人工项消解、开盘时窗、以及最终结论的阻断逻辑。

运行: python -m unittest tests.test_entry_rules_v050 -v
"""
from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "decision", "technical"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))

import check_entry_rules as cer  # noqa: E402
from indicators import sma_series  # noqa: E402


def gen(path: list[float], vol: float = 1_000_000.0) -> list[dict]:
    """按收盘价路径生成 K 线(开=前收,高/低略超出实体,等量)。

    高/低带随下标递增的微扰,避免转折点相邻两根高低完全相同
    (分形 pivot 要求窗口内唯一极值,真实行情鲜有完全相等)。
    """
    bars, prev = [], path[0]
    for i, px in enumerate(path):
        eps = 1e-6 * i
        bars.append({"open": prev, "close": px,
                     "high": max(prev, px) * (1.003 + eps),
                     "low": min(prev, px) * (0.997 - eps), "volume": vol})
        prev = px
    return bars


def ramp_to(start: float, target: float, n: int) -> list[float]:
    """从 start 经 n 根几何步进恰好到 target。"""
    r = (target / start) ** (1 / n)
    return [start * r ** (i + 1) for i in range(n)]


def run(path_or_bars, **opts):
    bars = path_or_bars if isinstance(path_or_bars, list) and \
        isinstance(path_or_bars[0], dict) else gen(path_or_bars)
    return cer.check_rules(cer.build_features(bars), opts)


OSC_TAIL = [100.0, 99.8, 100.1, 99.9, 100.2, 100.0]  # 结尾小幅震荡压低 RSI


def ramp(start: float, chg: float, n: int) -> list[float]:
    """从 start 起每根涨(chg>0)/跌(chg<0) chg 比例。"""
    out, p = [], start
    for _ in range(n):
        p *= 1 + chg
        out.append(p)
    return out


class TestDownNoBuy(unittest.TestCase):
    """下跌过程 12 不买中可自动判定的条目。"""

    def test_d1_new_close_low(self):
        path = [100] * 80 + ramp(99.5, -0.01, 6)
        r = run(path)
        self.assertEqual(r["rules"]["D1"]["status"], "triggered")
        self.assertEqual(r["verdict"], "❌ 不买")

    def test_d3_fib618_break(self):
        path = [50 + 50 * i / 59 for i in range(60)] + [100, 76.0, 71.0, 68.5]
        r = run(path)
        # 上行波段 50→100,61.8% 回撤位 ≈ 69.1,最新收盘 68.5 刚跌破
        self.assertEqual(r["rules"]["D3"]["status"], "triggered")
        self.assertIn("61.8%", r["rules"]["D3"]["evidence"])

    def test_d5_stop_undefined_at_lows(self):
        # 一路阴跌创新低 → 下方无支撑 → 无法定止损
        path = [100] * 40 + ramp(99, -0.01, 40)
        r = run(path)
        self.assertEqual(r["rules"]["D5"]["status"], "triggered")

    def test_d5_stop_beyond_tolerance(self):
        # 冲高 110 → 探底 88 → 反弹到 100: 支撑 ~88 距现价 ~12%
        path = ([100, 106, 110, 108] + ramp_to(108, 88, 18)
                + ramp_to(88, 100, 20) + OSC_TAIL)
        r = run(path, max_stop_pct=8.0)
        self.assertEqual(r["rules"]["D5"]["status"], "triggered")
        self.assertEqual(r["rules"]["U4"]["status"], "triggered")
        r2 = run(path, max_stop_pct=15.0)
        self.assertEqual(r2["rules"]["D5"]["status"], "clear")

    def test_d7_earnings_drop(self):
        path = [100] * 30 + ramp(99.5, -0.008, 30) + [70.0, 66.0]
        r = run(path, earnings_days=5)
        self.assertEqual(r["rules"]["D7"]["status"], "triggered")
        r2 = run(path, earnings_days=30)
        self.assertEqual(r2["rules"]["D7"]["status"], "clear")
        r3 = run(path)
        self.assertEqual(r3["rules"]["D7"]["status"], "manual")

    def test_d9_deep_drawdown(self):
        path = [100] * 40 + ramp(99.5, -0.012, 55)
        r = run(path)
        self.assertEqual(r["rules"]["D9"]["status"], "triggered")

    def test_d10_heat_with_crash(self):
        path = [100] * 40 + ramp(99.5, -0.018, 8)
        r = run(path, in_heat=True)
        self.assertEqual(r["rules"]["D10"]["status"], "triggered")
        r2 = run(path, in_heat=False)
        self.assertEqual(r2["rules"]["D10"]["status"], "clear")
        r3 = run(path)
        self.assertEqual(r3["rules"]["D10"]["status"], "manual")


class TestUpNoBuy(unittest.TestCase):
    """上涨过程 6 不买。"""

    def test_u5_rsi6_over_90(self):
        path = [50] * 40 + ramp(50.5, 0.03, 25)
        r = run(path)
        self.assertEqual(r["rules"]["U5"]["status"], "triggered")

    def test_u2_new_high_far_from_support(self):
        path = [50] * 40 + ramp(50.5, 0.03, 25)
        r = run(path)
        self.assertEqual(r["rules"]["U2"]["status"], "triggered")

    def test_u6_not_triggered_without_divergence(self):
        path = [50] * 40 + ramp(50.5, 0.03, 25)
        r = run(path)
        # 单边上涨没有顶背离 → U6 不触发(U5 触发)
        self.assertEqual(r["rules"]["U6"]["status"], "clear")


class TestBuySetups(unittest.TestCase):
    """高胜率买点结构 B1/B2/B4/B5/B6/B7。"""

    def _b1_bars(self):
        bars = [cer._bar(99, 100) for _ in range(40)]
        bars[20] = cer._bar(101, 102, h=103.5, vol=1_200_000)
        bars += [cer._bar(99.5, 100.2) for _ in range(8)]
        bars.append(cer._bar(101.5, 105.5, h=106, vol=3_000_000))
        bars += [cer._bar(104.6, 104.9, vol=1_200_000),
                 cer._bar(104.4, 104.8, vol=1_100_000),
                 cer._bar(104.5, 105.0, vol=1_000_000)]
        return bars

    def test_b1_breakout_pullback(self):
        r = run(self._b1_bars())
        self.assertEqual(r["rules"]["B1"]["status"], "matched")
        self.assertEqual(r["verdict"], "✅ 结构符合(纪律通过)")

    def test_b2_downtrend_line_breakout(self):
        path = ([100, 99, 98, 97, 96, 95, 94, 93, 92, 91,          # 下跌段1
                 92, 93, 94, 95,                                     # 反弹到 95(pivot高)
                 94, 93, 92, 91, 90, 89, 88, 87, 86, 85,             # 下跌段2
                 86, 87, 88, 89, 90,                                 # 反弹到 90(pivot高)
                 89, 88, 87, 86, 85, 84.5, 84, 84, 84, 84] +         # 下跌段3
                [87.0, 86.6, 87.2])                                  # 放量突破→真回踩→企稳
        bars = gen(path)
        bars[-3]["volume"] = 2_500_000  # 仅突破棒放量,回踩缩量
        r = run(bars)
        self.assertEqual(r["rules"]["B2"]["status"], "matched")
        self.assertIn("缩量回踩", r["rules"]["B2"]["evidence"])

    def test_b2_continuous_rise_is_not_pullback(self):
        """v0.5.3: 突破后单边拉升不构成「回踩」,不能匹配 B2。"""
        path = ([100, 99, 98, 97, 96, 95, 94, 93, 92, 91,
                 92, 93, 94, 95,
                 94, 93, 92, 91, 90, 89, 88, 87, 86, 85,
                 86, 87, 88, 89, 90,
                 89, 88, 87, 86, 85, 84.5, 84, 84, 84, 84] + [87.0, 87.5, 88.0])
        bars = gen(path)
        bars[-3]["volume"] = 2_500_000
        r = run(bars)
        self.assertEqual(r["rules"]["B2"]["status"], "none")

    def test_b4_w_bottom_neckline(self):
        path = ([100, 98, 96, 94, 92, 90, 88, 86.5,                 # 下跌
                 85.5, 85.8, 86.5, 87.5, 89, 90.5, 92, 93,           # 反弹(颈线区)
                 92, 90.5, 89, 87.5, 86.5, 85.9,                     # 回落至 L2
                 87.0, 88.5, 90.0, 91.0,                             # 起涨
                 94.5, 93.5])                                        # 突破 + 回踩
        bars = gen(path)
        bars[-2]["volume"] = 3_000_000  # 突破颈线放量
        bars[-1]["low"] = 93.0          # 回踩触及颈线附近
        r = run(bars)
        self.assertEqual(r["rules"]["B4"]["status"], "matched")

    def test_b5_first_ma5_pullback(self):
        path = [50 * (1.01 ** i) for i in range(55)]  # 连续上涨
        bars = gen(path)
        prev_close = path[-1]
        ma5 = sma_series([b["close"] for b in bars], 5)[-1]
        bars.append({"open": prev_close, "close": prev_close * 0.995,
                     "high": prev_close * 1.002, "low": ma5 * 0.998,
                     "volume": 1_000_000})
        r = run(bars)
        self.assertEqual(r["rules"]["B5"]["status"], "matched")

    def test_b6_bullish_engulfing(self):
        path = [100] * 20 + ramp(99, -0.012, 25)  # 阴跌
        bars = gen(path)
        prev_close = path[-1]
        # 前一日: 缩量阴线创近期低点
        bars.append({"open": prev_close * 1.001, "close": prev_close * 0.992,
                     "high": prev_close * 1.004, "low": prev_close * 0.985,
                     "volume": 500_000})
        # 今日: 放量大阳吞没,上影极短
        p_open, p_close = bars[-1]["open"], bars[-1]["close"]
        bars.append({"open": p_close * 0.998, "close": p_open * 1.01,
                     "high": p_open * 1.011, "low": p_close * 0.997,
                     "volume": 2_200_000})
        r = run(bars)
        self.assertEqual(r["rules"]["B6"]["status"], "matched")

    def test_b7_hammer_after_shrink_low(self):
        path = [100] * 20 + ramp(99, -0.012, 25)
        bars = gen(path)
        prev_close = path[-1]
        bars.append({"open": prev_close * 1.001, "close": prev_close * 0.992,
                     "high": prev_close * 1.004, "low": prev_close * 0.985,
                     "volume": 500_000})
        # 今日标准锤子: 下影≥2倍实体,上影≈0,收盘位于区间上部,放量
        o, c = prev_close * 0.992, prev_close * 0.997
        bars.append({"open": o, "close": c, "high": c * 1.0005,
                     "low": o - (c - o) * 2.6, "volume": 2_000_000})
        r = run(bars)
        self.assertEqual(r["rules"]["B7"]["status"], "matched")


class TestGateAndVerdict(unittest.TestCase):
    """B0 盈亏比闸门与最终结论。"""

    def _range_bars(self, hi: float, lo: float, end: float):
        """老的结构位: 先冲高 hi 再探低 lo,现价 end。"""
        path = ([hi] * 6 + [hi - 1] * 8 + ramp(hi - 2, -0.01, 20)
                + ramp(None if lo is None else lo * 1.02, 0.01, 20))
        path = [p for p in path if p is not None]
        return gen(path + [end])

    def test_b0_fail_blocks_entry(self):
        # 压力 110 / 支撑 88 / 现价 100 → 盈亏比 10:12 < 1 → 不买
        path = ([100, 106, 110, 108] + ramp_to(108, 88, 18)
                + ramp_to(88, 100, 20) + OSC_TAIL)
        r = run(path)
        self.assertEqual(r["rules"]["B0"]["status"], "fail")
        self.assertEqual(r["verdict"], "❌ 不买")
        self.assertTrue(any(x.startswith("B0") for x in r["verdict_reasons"]))

    def test_b0_pass(self):
        # 压力 120 / 支撑 96 / 现价 100 → 盈亏比 20:4 = 5 → 通过
        path = ([100, 112, 120, 118] + ramp_to(118, 96, 18)
                + ramp_to(96, 100, 18) + OSC_TAIL)
        r = run(path)
        self.assertEqual(r["rules"]["B0"]["status"], "pass")

    def test_verdict_watch_when_no_setup(self):
        r = run([100 + (i % 7) * 0.2 for i in range(80)])
        self.assertIn(r["verdict"], ("⏸️ 观望", "❌ 不买"))

    def test_manual_rules_listed_in_verdict(self):
        # 有结构的震荡序列(非退化平盘): 无新低新高、有支撑压力、RSI 中性
        path = [100 + ((i % 9) - 4) * 0.7 for i in range(80)]
        path[-1] = 99.5
        r = run(path)
        for k in ("D6", "D8", "D9", "D11"):
            self.assertEqual(r["rules"][k]["status"], "manual")
        self.assertEqual(r["triggered"], [])
        self.assertEqual(r["verdict"], "⏸️ 观望")
        self.assertTrue(any("待人工确认" in x for x in r["verdict_reasons"]))

    def test_manual_answers_resolve(self):
        bars = [cer._bar(99, 100) for _ in range(60)]
        r = cer.check_rules(cer.build_features(bars), {
            "sector_top_decline": "yes", "recent_stopout": "yes",
            "familiar": "no", "prepost_move": "yes"})
        self.assertEqual(r["rules"]["D6"]["status"], "triggered")
        self.assertEqual(r["rules"]["D8"]["status"], "triggered")
        self.assertEqual(r["rules"]["D9"]["status"], "triggered")
        self.assertEqual(r["rules"]["D11"]["status"], "triggered")
        # 只有可答的人工项被消解,D7/D10/D12 仍待数据
        self.assertNotIn("D6", r["manual"])
        self.assertNotIn("D8", r["manual"])
        self.assertNotIn("D9", r["manual"])
        self.assertNotIn("D11", r["manual"])
        r2 = cer.check_rules(cer.build_features(bars), {
            "sector_top_decline": "no", "recent_stopout": "no",
            "familiar": "yes", "prepost_move": "no"})
        self.assertEqual(r2["rules"]["D6"]["status"], "clear")
        self.assertEqual(r2["rules"]["D9"]["status"], "clear")


class TestD12OpenWindow(unittest.TestCase):
    """D12 语义(v0.5.2 确认): 盘前 30 分钟(9:00-9:30)不买,非开盘后 30 分钟。"""

    def test_in_premarket_window_triggered(self):
        from datetime import datetime as dt
        r = run([100] * 60, now=dt(2026, 9, 29, 9, 15), market="HK")
        self.assertEqual(r["rules"]["D12"]["status"], "triggered")
        self.assertIn("盘前30分钟", r["rules"]["D12"]["evidence"])

    def test_after_window_clear(self):
        from datetime import datetime as dt
        # 9:45 属于开盘后,按确认后的语义不在禁买窗口
        r = run([100] * 60, now=dt(2026, 9, 29, 9, 45), market="HK")
        self.assertEqual(r["rules"]["D12"]["status"], "clear")
        r2 = run([100] * 60, now=dt(2026, 9, 29, 11, 0), market="US")
        self.assertEqual(r2["rules"]["D12"]["status"], "clear")

    def test_holiday_clear(self):
        from datetime import datetime as dt
        r = run([100] * 60, now=dt(2026, 11, 26, 9, 15), market="US",
                closed_dates={"2026-11-26"})
        self.assertEqual(r["rules"]["D12"]["status"], "clear")
        self.assertIn("休市日", r["rules"]["D12"]["evidence"])

    def test_no_time_manual(self):
        r = run([100] * 60)
        self.assertEqual(r["rules"]["D12"]["status"], "manual")


class TestEngineRobustness(unittest.TestCase):
    def test_minimal_bars_no_crash(self):
        bars = [cer._bar(99, 100) for _ in range(30)]
        r = cer.check_rules(cer.build_features(bars))
        self.assertIn("verdict", r)
        self.assertEqual(len(r["rules"]), 28)

    def test_rsi_series_known_values(self):
        # 6 连涨 → RSI(6) 应接近 100;6 连跌 → 接近 0
        up = cer.rsi_series([100 + i for i in range(20)], 6)
        self.assertGreater(up[-1], 95)
        dn = cer.rsi_series([100 - i for i in range(20)], 6)
        self.assertLess(dn[-1], 5)

    def test_pivot_and_cluster(self):
        h = [10, 11, 12, 13, 14, 13, 12, 11, 10, 10.5, 11, 11.5, 12, 11.5, 11, 10.5, 10]
        l = [x - 2 for x in h]
        piv = cer.find_pivots(h, l, k=3)
        highs = [p for p in piv if p["kind"] == "high"]
        self.assertEqual(highs[0]["price"], 14.0)
        lows = [p for p in piv if p["kind"] == "low"]
        self.assertEqual(lows[0]["price"], 8.0)


# ===========================================================================
# v0.5.1 修复回归(外部代码审查确认的 10+1 项缺陷)
# ===========================================================================

class TestV051Fixes(unittest.TestCase):
    """每条用例对应一项已确认并修复的缺陷。"""

    def setUp(self):
        self._keys = cer.get_heat_rank_keys
        self._rank = cer.get_heat_rank

    def tearDown(self):
        cer.get_heat_rank_keys = self._keys
        cer.get_heat_rank = self._rank

    def test_d10_heat_rank_lists_key(self):
        """get_heat_rank 返回键名是 lists(复数),读错键会让热度榜永远未命中。"""
        cer.get_heat_rank_keys = lambda m: [{"key": "k"}]
        cer.get_heat_rank = lambda key, count=20: {"lists": [{"symbol": "AAPL.US"}]}
        self.assertTrue(cer._in_heat_rank("AAPL.US"))
        cer.get_heat_rank = lambda key, count=20: {"lists": [{"symbol": "TSLA.US"}]}
        self.assertFalse(cer._in_heat_rank("AAPL.US"))
        cer.get_heat_rank = lambda key, count=20: (_ for _ in ()).throw(RuntimeError)
        self.assertIsNone(cer._in_heat_rank("AAPL.US"))

    def test_b8_manual_visible_in_verdict(self):
        """B8 待确认板块时不能被结论吞没成「未出现任何买点」。"""
        path = [100.0, 99.0, 98.0, 99.0, 100.0] * 8 + [99.0, 100.0, 101.0, 100.0]
        bars = gen(path)
        bars[-1] = cer._bar(100.0, 104.0, h=104.2, lo=99.8, vol=3_000_000)
        opts = {"sector_breakout": None, "sector_top_decline": "no",
                "recent_stopout": "no", "familiar": "yes", "prepost_move": "no",
                "earnings_days": 30, "in_heat": False}
        r = cer.check_rules(cer.build_features(bars), opts)
        self.assertEqual(r["rules"]["B8"]["status"], "manual")
        self.assertIn("B8", r["manual"])
        self.assertIn("潜在买点", "".join(r["verdict_reasons"]))
        # 回答「板块当日突破」后转为 matched
        r2 = cer.check_rules(cer.build_features(gen(path) + [
            cer._bar(100.0, 104.0, h=104.2, lo=99.8, vol=3_000_000)]),
            dict(opts, sector_breakout="yes"))
        self.assertEqual(r2["rules"]["B8"]["status"], "matched")

    def test_b5_ma10_pullback_matched(self):
        """经典 10 日线回踩(下影穿 5 日线、收盘站上 10 日线)必须成立。"""
        path = [50 * (1.01 ** i) for i in range(55)]
        bars = gen(path)
        c = [b["close"] for b in bars]
        ma5 = sma_series(c, 5)[-1]
        ma10 = sma_series(c, 10)[-1]
        close = (ma5 + ma10) / 2  # 收盘介于两线之间(5 日线下方)
        # 特征层的 MA10 含新 bar,须按含新收盘的口径定下影低点
        ma10f = sma_series(c + [close], 10)[-1]
        open_ = close * 1.004  # 跳空小实体阴线,避免大实体吞掉下影
        bars.append({"open": open_, "close": close, "high": open_ * 1.001,
                     "low": ma10f * 0.998, "volume": 1_000_000})
        self.assertLess(close, ma5)
        r = cer.check_rules(cer.build_features(bars))
        self.assertEqual(r["rules"]["B5"]["status"], "matched")
        self.assertIn("10日", r["rules"]["B5"]["evidence"])

    def test_b5_break_below_ma10_is_none(self):
        path = [50 * (1.01 ** i) for i in range(55)]
        bars = gen(path)
        c = [b["close"] for b in bars]
        ma10 = sma_series(c, 10)[-1]
        bars.append({"open": path[-1], "close": ma10 * 0.99,
                     "high": path[-1] * 1.002, "low": ma10 * 0.997,
                     "volume": 1_000_000})
        r = cer.check_rules(cer.build_features(bars))
        self.assertEqual(r["rules"]["B5"]["status"], "none")

    def test_strong_support_retest_not_dropped(self):
        """近期刚被回踩测试的历史强支撑(touches≥2)不能被结构位过滤整簇丢弃。"""
        path = ([100.0, 102.0, 100.5, 101.5] * 5
                + [102.0, 106.0, 112.0, 118.0]
                + ramp_to(117.9, 100.4, 14)
                + [101.0, 102.0, 103.0, 103.5])
        f = cer.build_features(gen(path))
        self.assertTrue(f["supports"], "回踩强支撑后 supports 不应为空")
        r = cer.check_rules(f)
        self.assertEqual(r["rules"]["D5"]["status"], "clear")

    def test_b6_requires_today_volume(self):
        """B6 的「放量」必须校验当日量:无量吞没不成立。"""
        path = [100] * 20 + ramp_to(99.5, 82.0, 25)
        base = gen(path)
        prev = base[-1]["close"]
        p_open, p_close = prev * 1.001, prev * 0.992
        for vol, expect in ((1, "none"), (2_200_000, "matched")):
            bars = list(base)
            bars.append({"open": p_open, "close": p_close, "high": prev * 1.004,
                         "low": prev * 0.985, "volume": 500_000})
            bars.append({"open": p_close * 0.998, "close": p_open * 1.01,
                         "high": p_open * 1.011, "low": p_close * 0.997,
                         "volume": vol})
            r = cer.check_rules(cer.build_features(bars))
            self.assertEqual(r["rules"]["B6"]["status"], expect,
                             f"今日量 {vol} 应为 {expect}")

    def test_rsi_flat_series_neutral(self):
        """横盘无波动 RSI 应为中性 50,而不是 100(否则误报 U5 超买)。"""
        self.assertEqual(cer.rsi_series([100.0] * 20, 6)[-1], 50.0)
        r = run(gen([100.0] * 60))
        self.assertEqual(r["rules"]["U5"]["status"], "clear")

    def test_b2_needs_post_breakout_bar(self):
        """突破趋势线当天不能自称「回踩不破」——必须至少有一根后续棒。"""
        path = ([100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 92, 93, 94, 95,
                 94, 93, 92, 91, 90, 89, 88, 87, 86, 85, 86, 87, 88, 89, 90,
                 89, 88, 87, 86, 85, 84.5, 84, 84, 84, 84] + [87.5])
        bars = gen(path)
        bars[-1]["volume"] = 2_500_000  # 突破棒即最新一根,无回踩棒
        r = cer.check_rules(cer.build_features(bars))
        self.assertEqual(r["rules"]["B2"]["status"], "none")

    def test_d12_weekend_clear(self):
        from datetime import datetime as dt
        self.assertEqual(cer._check_open_window(
            {"now": dt(2026, 10, 3, 9, 45), "market": "US"})["status"], "clear")
        self.assertEqual(cer._check_open_window(
            {"now": dt(2026, 10, 4, 9, 45), "market": "HK"})["status"], "clear")

    def test_d3_second_break_detected(self):
        """跌破→反抽→二次跌破:穿越式检测应捕捉(c[n-4] 硬比较会漏)。"""
        path = ramp_to(50, 100, 60) + [68.0, 72.0, 68.5]
        r = run(path)
        self.assertEqual(r["rules"]["D3"]["status"], "triggered")
        self.assertIn("61.8%", r["rules"]["D3"]["evidence"])

    def test_divergence_stale_ignored(self):
        """陈年背离(第二 pivot 超过 25 根)不作数。"""
        fresh = (ramp_to(50, 86, 14) + ramp_to(85.5, 79, 3) + ramp_to(79.3, 88.5, 4)
                 + ramp_to(88.2, 81.5, 3) + ramp_to(81.7, 89.4, 4)
                 + ramp_to(89.2, 83, 3) + ramp_to(83.2, 90.2, 4)
                 + ramp_to(90.0, 84.5, 3))
        f1 = cer.build_features(gen(fresh))
        self.assertIsNotNone(f1["bearish_div"], "正向对照应检出顶背离")
        f2 = cer.build_features(gen(fresh + [84.5] * 42))
        self.assertIsNone(f2["bearish_div"], "陈年背离应被时效窗口过滤")

    def test_d2_strong_support_break_near_res(self):
        """刚跌破强支撑(被跌破的位在现价上方,须扫全量 levels)且紧邻压力。"""
        path = ([100] * 5 + ramp_to(99.5, 90, 6) + ramp_to(90.5, 93, 4)
                + ramp_to(92.5, 90.5, 5) + ramp_to(91, 95, 4)
                + [92.0, 90.0, 89.5])
        r = run(path)
        self.assertEqual(r["rules"]["D2"]["status"], "triggered")
        self.assertEqual(r["rules"]["D3"]["status"], "triggered")
        self.assertIn("颈线", r["rules"]["D3"]["evidence"])


class TestBlindSpotSetups(unittest.TestCase):
    """v0.5.0 审查指出的测试盲区: B3/B9 买点与 D4/U1/U3 不买规则。"""

    def test_b3_bull_flag(self):
        path = ([100.0] * 30 + [102.0, 105.0, 108.0, 111.0]     # 旗杆 +8.8%
                + [110.5, 110.0, 109.5, 109.0] + [113.0])       # 旗面缩量 + 放量破旗面
        bars = gen(path)
        for i in range(30, 34):
            bars[i]["volume"] = 1_500_000      # 杆放量
        for i in range(34, 38):
            bars[i]["volume"] = 500_000        # 面缩量
        bars[-1]["volume"] = 2_500_000         # 突破棒
        r = cer.check_rules(cer.build_features(bars))
        self.assertEqual(r["rules"]["B3"]["status"], "matched")

    def test_b9_fib_oversold_div_stop(self):
        """主升段回撤守 61.8% + RSI6 超卖 + 底背离 + 止跌形态,四者齐备。"""
        bars = gen(ramp_to(50, 100, 40))
        prev = 100.0

        def app(c, lo, vol=1_000_000):
            nonlocal prev
            bars.append({"open": prev, "close": c, "high": max(prev, c) * 1.004,
                         "low": lo, "volume": vol})
            prev = c

        for k in range(1, 13):                       # 第一段下跌 12×-2% → RSI≈10
            c = 99.5 * 0.98 ** k
            app(c, min(prev, c) * 0.996 - 0.25)
        b1 = prev
        for c in (b1 * 1.012, b1 * 1.012 ** 2):      # 弱反弹
            app(c, prev * 1.001)
        for _ in range(4):                           # 第二段 4×-1.5% → 更低低点,RSI≈15
            app(prev * 0.985, min(prev, prev * 0.985) * 0.996 - 0.2)
        b2 = prev
        for i in range(3):                           # 三根十字平底(低点略抬)
            app(b2 + 0.01 * i, b2 * 1.0005 + 0.01 * i)
        bars.append({"open": prev, "close": b2 + 0.05, "high": b2 + 0.06,
                     "low": b2 - 0.5, "volume": 2_200_000})   # 小实体长下影锤子
        r = cer.check_rules(cer.build_features(bars))
        self.assertEqual(r["rules"]["B9"]["status"], "matched")

    def test_d4_shrink_rebound(self):
        bars = gen([100] * 20 + ramp_to(99.5, 80.0, 25))
        prev = bars[-1]["close"]
        bars.append({"open": prev, "close": prev * 1.008, "high": prev * 1.012,
                     "low": prev * 0.998, "volume": 400_000})
        r = cer.check_rules(cer.build_features(bars))
        self.assertEqual(r["rules"]["D4"]["status"], "triggered")

    def test_u1_shrink_new_high(self):
        bars = gen(ramp_to(50, 99.4, 59))
        bars.append({"open": 99.4, "close": 99.8, "high": 99.9, "low": 99.3,
                     "volume": 400_000})
        r = cer.check_rules(cer.build_features(bars))
        self.assertEqual(r["rules"]["U1"]["status"], "triggered")

    def test_u3_breakout_near_strong_res(self):
        path = (ramp_to(100, 106.5, 9) + ramp_to(106.3, 102, 7)
                + ramp_to(102.2, 106.5, 7) + ramp_to(106.3, 101.5, 8)
                + ramp_to(101.7, 104.3, 5) + ramp_to(104.1, 102, 4)
                + ramp_to(102.2, 104.3, 4) + ramp_to(104.1, 102.2, 3)
                + [103.2, 104.0, 104.8])
        r = run(path)
        self.assertEqual(r["rules"]["U3"]["status"], "triggered")


class TestV052Upgrades(unittest.TestCase):
    """v0.5.2 第四档补齐: D10 小市值自动、B8 板块涨幅自动、CLI 数据层。"""

    def test_d10_smallcap_gate(self):
        path = [100] * 40 + ramp_to(99.5, 88.0, 5)  # 近5日累计大跌(5日窗全覆盖)
        # 小市值 + 热度 + 大跌 → 触发
        r = run(path, in_heat=True, smallcap=True)
        self.assertEqual(r["rules"]["D10"]["status"], "triggered")
        self.assertIn("小市值", r["rules"]["D10"]["evidence"])
        # 大市值 + 热度 + 大跌 → 明确放行
        r2 = run(path, in_heat=True, smallcap=False)
        self.assertEqual(r2["rules"]["D10"]["status"], "clear")
        self.assertIn("大市值", r2["rules"]["D10"]["evidence"])
        # 市值未知 → 维持旧行为(触发+提示自行确认)
        r3 = run(path, in_heat=True, smallcap=None)
        self.assertEqual(r3["rules"]["D10"]["status"], "triggered")
        self.assertIn("市值未知", r3["rules"]["D10"]["evidence"])

    def test_b8_sector_detail_in_evidence(self):
        path = [100.0, 99.0, 98.0, 99.0, 100.0] * 8 + [99.0, 100.0, 101.0, 100.0]
        bars = gen(path)
        bars[-1] = cer._bar(100.0, 104.0, h=104.2, lo=99.8, vol=3_000_000)
        r = cer.check_rules(cer.build_features(bars), {
            "sector_breakout": "yes", "sector_detail": "行业「半导体」今日 4.2%,阈值 3%"})
        self.assertIn("半导体", r["rules"]["B8"]["evidence"])

    def test_auto_sector_breakout_paths(self):
        orig = cer.get_industry_rank
        try:
            rank = [{"name": "板块涨幅榜", "lists": [
                {"name": "海运港口-运营商", "chg": "0.1544",
                 "leading_ticker": "SGLY", "leading_name": "Singularity"},
                {"name": "半导体", "chg": "0.021",
                 "leading_ticker": "NVDA", "leading_name": "英伟达"},
            ]}]
            cer.get_industry_rank = lambda market="US": rank
            # ① --sector 指名,涨幅超阈值 → yes
            ans, note = cer._auto_sector_breakout("GOOG.US", "US", "半导体", 0.03)
            self.assertEqual(ans, "no")
            self.assertIn("半导体", note)
            ans2, _ = cer._auto_sector_breakout("GOOG.US", "US", "海运", 0.03)
            self.assertEqual(ans2, "yes")
            # ② 领涨股反查
            ans3, note3 = cer._auto_sector_breakout("SGLY.US", "US", None, 0.03)
            self.assertEqual(ans3, "yes")
            # ③ 无法映射 → None
            ans4, note4 = cer._auto_sector_breakout("GOOG.US", "US", None, 0.03)
            self.assertIsNone(ans4)
            self.assertIn("--sector", note4)
            # ④ 指名但榜单没有 → None
            ans5, _ = cer._auto_sector_breakout("GOOG.US", "US", "航天", 0.03)
            self.assertIsNone(ans5)
            # ⑤ 数据源挂 → None
            cer.get_industry_rank = lambda market="US": (_ for _ in ()).throw(RuntimeError)
            ans6, _ = cer._auto_sector_breakout("GOOG.US", "US", "半导体", 0.03)
            self.assertIsNone(ans6)
        finally:
            cer.get_industry_rank = orig

    def test_is_small_cap(self):
        orig_run, orig_price = cer.run_cli, cer.get_underlying_price
        try:
            # US: 10亿股 × $50 = $500亿 → 非小市值(阈值 20亿)
            cer.run_cli = lambda *a, **k: [{"symbol": "X.US", "total_shares": "1e9"}]
            cer.get_underlying_price = lambda s: 50.0
            self.assertFalse(cer._is_small_cap("X.US", 2e9))
            # US: 1000万股 × $5 = $5000万 → 小市值
            cer.run_cli = lambda *a, **k: [{"symbol": "Y.US", "total_shares": "10000000"}]
            cer.get_underlying_price = lambda s: 5.0
            self.assertTrue(cer._is_small_cap("Y.US", 2e9))
            # HK: 20亿股 × HK$10 = HK$200亿 ≈ $25.6亿 → 非小市值
            cer.run_cli = lambda *a, **k: [{"symbol": "Z.HK", "total_shares": "2e9"}]
            cer.get_underlying_price = lambda s: 10.0
            self.assertFalse(cer._is_small_cap("Z.HK", 2e9))
            # 查询失败 → None
            cer.run_cli = lambda *a, **k: (_ for _ in ()).throw(RuntimeError)
            self.assertIsNone(cer._is_small_cap("X.US", 2e9))
        finally:
            cer.run_cli = orig_run
            cer.get_underlying_price = orig_price

    def test_closed_dates_parse(self):
        orig = cer.get_finance_calendar
        try:
            cer.get_finance_calendar = lambda **k: [
                {"date": "2026-11-26", "infos": [
                    {"content": "感恩节", "ext": {"holiday_date": "2026-11-26",
                                                 "holiday_type": "full_day"}}]},
                {"date": "2026-12-25", "infos": [{"content": "圣诞", "ext": {}}]},
            ]
            got = cer._closed_dates("US")
            self.assertEqual(got, {"2026-11-26", "2026-12-25"})
            cer.get_finance_calendar = lambda **k: (_ for _ in ()).throw(RuntimeError)
            self.assertEqual(cer._closed_dates("US"), set())
        finally:
            cer.get_finance_calendar = orig


if __name__ == "__main__":
    unittest.main()
