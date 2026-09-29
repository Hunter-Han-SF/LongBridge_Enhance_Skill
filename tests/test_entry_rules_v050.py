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
                [87.0, 87.5, 88.0])                                  # 放量突破并站稳
        bars = gen(path)
        for i in (len(bars) - 3, len(bars) - 2, len(bars) - 1):
            bars[i]["volume"] = 2_500_000  # 突破放量
        r = run(bars)
        self.assertEqual(r["rules"]["B2"]["status"], "matched")

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
        r = run([100] * 80)
        for k in ("D6", "D8", "D9", "D11"):
            self.assertEqual(r["rules"][k]["status"], "manual")
        self.assertTrue(any("待人工确认" in x for x in r["verdict_reasons"])
                        or r["verdict"] == "❌ 不买")

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
    def test_in_window_triggered(self):
        r = run([100] * 60, now=__import__("datetime").datetime(2026, 9, 29, 9, 45),
                market="HK")
        self.assertEqual(r["rules"]["D12"]["status"], "triggered")

    def test_outside_window_clear(self):
        r = run([100] * 60, now=__import__("datetime").datetime(2026, 9, 29, 11, 0),
                market="HK")
        self.assertEqual(r["rules"]["D12"]["status"], "clear")
        r2 = run([100] * 60, now=__import__("datetime").datetime(2026, 9, 29, 9, 45, 30),
                 market="HK")
        self.assertEqual(r2["rules"]["D12"]["status"], "triggered")

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


if __name__ == "__main__":
    unittest.main()
