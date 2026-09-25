"""v0.4.1 缺陷修复的回归测试。

覆盖三项修复:
  1. MACD cross 序列未对齐(旧逻辑用 signal-1 根之前的 DIF 与当期 DEA 比较,
     随机数据下约 15% 概率漏判金叉/死叉)
  2. 资金面 3e6 固定金额阈值饱和(改为 |大单净额|/当日大单总流量 的尺度无关占比)
  3. Windows 管道/重定向输出退回 CP936 时 print emoji 抛 UnicodeEncodeError
     (common.py 导入时统一 reconfigure stdout/stderr 为 UTF-8)

运行: python -m unittest tests.test_fixes_v041 -v
"""
from __future__ import annotations

import os
import random
import subprocess
import sys
import unittest

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "technical", "decision"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))
sys.path.insert(0, _HERE)

import indicators  # noqa: E402
import analyze_buy_sell as dash  # noqa: E402


def _aligned_cross(closes: list[float]) -> str | None:
    """独立参考实现: 显式尾部对齐后在近 3 根内找 DIF/DEA 交叉。"""
    ef = indicators.ema_series(closes, 12)
    es = indicators.ema_series(closes, 26)
    dif = [a - b for a, b in zip(ef, es) if a is not None and b is not None]
    dea = [d for d in indicators.ema_series(dif, 9) if d is not None]
    dif_aligned = dif[-len(dea):]
    cross = None
    for k in range(max(1, len(dea) - 3), len(dea)):
        if dif_aligned[k - 1] <= dea[k - 1] and dif_aligned[k] > dea[k]:
            cross = "golden"
        elif dif_aligned[k - 1] >= dea[k - 1] and dif_aligned[k] < dea[k]:
            cross = "death"
    return cross


class TestMacdCrossAlignment(unittest.TestCase):
    """macd() 的 cross 必须与显式对齐的参考实现一致。"""

    def test_cross_matches_aligned_reference(self):
        random.seed(42)
        scenarios = [
            # 长期阴跌后近几根急涨 → golden;涨后急跌 → death;单边缓涨 → None
            [100 * (0.995 ** i) for i in range(130)]
            + [100 * (0.995 ** 130) * (1.05 ** j) for j in range(1, 8)],
            [100 * (1.005 ** i) for i in range(130)]
            + [100 * (1.005 ** 130) * (0.94 ** j) for j in range(1, 8)],
            [100 * (1.004 ** i) for i in range(150)],
        ]
        for _ in range(10):  # 随机游走(固定种子,可复现)
            p, s = 100.0, []
            for _i in range(150):
                p *= 1 + random.gauss(0, 0.02)
                s.append(p)
            scenarios.append(s)
        for idx, closes in enumerate(scenarios):
            with self.subTest(scene=idx):
                self.assertEqual(indicators.macd(closes)["cross"],
                                 _aligned_cross(closes))

    def test_dif_dea_hist_latest_consistent(self):
        closes = [100 * (1.004 ** i) for i in range(150)]
        r = indicators.macd(closes)
        # hist 最新值应等于对齐后的 dif-dea(旧实现 hist 本就正确,守恒不变)
        self.assertAlmostEqual(r["hist"], r["dif"] - r["dea"], places=10)


class TestCapitalScoreScaleFree(unittest.TestCase):
    """资金面强度用大单失衡占比,大盘股小额占比不再瞬间打满。"""

    def setUp(self):
        self._orig_cap = dash.get_capital_flow_snapshot
        self._orig_st = dash.get_short_trades

    def tearDown(self):
        dash.get_capital_flow_snapshot = self._orig_cap
        dash.get_short_trades = self._orig_st

    def _run(self, cap_data):
        dash.get_capital_flow_snapshot = lambda s: cap_data
        dash.get_short_trades = lambda s, count=10: {}
        bulls, bears = [], []
        return dash._dim_capital("TEST.US", bulls, bears)

    def test_large_cap_low_imbalance_not_saturated(self):
        # AAPL 级: 净流入 $50M,当日大单流量 $1.15B → 失衡仅 4.3%,旧逻辑=100
        score, _ = self._run({"net": {"large": 5e7},
                              "capital_in": {"large": 6e8},
                              "capital_out": {"large": 5.5e8}})
        self.assertGreater(score, 50.0)
        self.assertLess(score, 100.0)

    def test_extreme_imbalance_full_score(self):
        score, _ = self._run({"net": {"large": 4e8},
                              "capital_in": {"large": 7e8},
                              "capital_out": {"large": 3e8}})
        self.assertEqual(score, 100.0)

    def test_zero_net_no_division_error(self):
        score, _ = self._run({"net": {"large": 0}, "capital_in": {}, "capital_out": {}})
        self.assertEqual(score, 50.0)


class TestUtf8OutputProtection(unittest.TestCase):
    """import common 后,即使环境强制 GBK 编码流也能打印 emoji。"""

    def test_emoji_print_survives_gbk_stream(self):
        code = (f"import sys; sys.path.insert(0, r'{_SCRIPTS}'); import common; "
                "print('信号 🟢 中文')")
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        env["PYTHONIOENCODING"] = "gbk"  # 模拟中文 Windows 管道退回 CP936
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, msg=r.stderr.decode("gbk", "replace"))


if __name__ == "__main__":
    unittest.main()
