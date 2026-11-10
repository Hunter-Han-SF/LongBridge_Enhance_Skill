"""v0.6.1 修复回归:服务端 calc-index theta 死值 → 本地 BS 补算 + 来源标注。

实测(2026-11-10,CLI 0.26.0) Longbridge calc-index 的 theta 恒返回
-0.000/-0.001,同一链上不随行权价变化(delta/gamma/vega/rho 正常)。
修复前 get_option_quote 静默透传 0 并显示为真实数据;修复后:
  - theta_source=server        服务端非零值,直接采信
  - theta_source=bs_backfill   服务端死值 → 本地 BS 补算
  - theta_source=black_scholes 原生整体失败 → 全套 BS(原有路径)
  - theta_source=dead_zero     服务端死值且无法补算(无 IV/到期/BS 拒算)

运行: python -m unittest tests.test_fixes_v061 -v
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "quote"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))

import common  # noqa: E402
import get_option_quote as goq  # noqa: E402

# 服务端真实返回形态的夹具:theta 为 -0.0(即 CLI 表格里的 -0.000)
_DEAD_THETA_METRICS = {
    "delta": -0.552, "gamma": 0.015, "theta": -0.0,
    "vega": 0.186, "rho": -0.078, "iv": 0.574, "oi": 2662,
}
_ALIVE_THETA_METRICS = dict(_DEAD_THETA_METRICS, theta=-0.2024)


def _patch_quote(monkey_metrics, chain=None, price=178.67):
    """按仓库惯例保存原函数→打桩→finally 还原;返回 (result, stdout)。"""
    orig = (goq.run_cli, goq.get_option_chain, goq.get_underlying_price,
            goq.get_option_contract_metrics)
    goq.run_cli = lambda *a, **k: None
    goq.get_option_chain = lambda u, e: chain or []
    goq.get_underlying_price = lambda u: price
    goq.get_option_contract_metrics = lambda syms: {syms[0]: monkey_metrics(syms[0])}
    return orig


def _restore(orig):
    (goq.run_cli, goq.get_option_chain, goq.get_underlying_price,
     goq.get_option_contract_metrics) = orig


class TestThetaDeadFieldBackfill(unittest.TestCase):
    """服务端 theta==0 时必须 BS 补算并标注,不再把死值当真实数据透传。"""

    def test_dead_theta_backfilled_with_bs(self):
        orig = _patch_quote(lambda sym: dict(_DEAD_THETA_METRICS))
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = goq.get_quote("NVDA.US", "2027-01-15", 185.0, "PUT",
                                  rate=0.045, output_json=False, quiet=True)
            # 原生路径保持不变,只有 theta 被替换
            self.assertEqual(r["greeks_source"], "native")
            self.assertEqual(r["greeks"]["delta"], -0.552)
            self.assertEqual(r["theta_source"], "bs_backfill")
            # 与本地 BS 引擎逐位一致(同参数自洽,不依赖运行日期)
            expected = common.bs_greeks(
                178.67, 185.0, common.days_to_years("2027-01-15"),
                0.045, 0.574, "P")["theta"]
            self.assertEqual(r["greeks"]["theta"], expected)
            self.assertLess(r["greeks"]["theta"], -0.05)  # 量级合理,非 0
        finally:
            _restore(orig)

    def test_dead_theta_annotation_printed(self):
        orig = _patch_quote(lambda sym: dict(_DEAD_THETA_METRICS))
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                goq.get_quote("NVDA.US", "2027-01-15", 185.0, "PUT", quiet=False)
            out = buf.getvalue()
            self.assertIn("BS补算(服务端死值)", out)
            self.assertNotIn("theta = 0.0000", out)
        finally:
            _restore(orig)

    def test_alive_theta_kept_from_server(self):
        """服务端 theta 非零(未来修复或换端点)时直接采信,不触发补算。"""
        orig = _patch_quote(lambda sym: dict(_ALIVE_THETA_METRICS))
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = goq.get_quote("NVDA.US", "2027-01-15", 185.0, "PUT", quiet=True)
            self.assertEqual(r["theta_source"], "server")
            self.assertEqual(r["greeks"]["theta"], -0.2024)
            buf_out = buf.getvalue()
            self.assertNotIn("BS补算", buf_out)
        finally:
            _restore(orig)

    def test_dead_theta_no_iv_marks_dead_zero(self):
        """无 IV 可补算时保留 0 但必须标注 dead_zero,不得伪装成真实数据。"""
        m = {k: v for k, v in _DEAD_THETA_METRICS.items() if k != "iv"}
        orig = _patch_quote(lambda sym: m, chain=[])
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = goq.get_quote("NVDA.US", "2027-01-15", 185.0, "PUT", quiet=False)
            self.assertEqual(r["greeks_source"], "native")
            self.assertEqual(r["greeks"]["theta"], 0.0)
            self.assertEqual(r["theta_source"], "dead_zero")
            self.assertIn("服务端死值,无有效数据", buf.getvalue())
        finally:
            _restore(orig)

    def test_expired_dead_theta_no_backfill(self):
        """已到期合约不做补算(T<=0,BS 会退化),theta 保持 0 且标记 dead_zero。"""
        orig = _patch_quote(lambda sym: dict(_DEAD_THETA_METRICS, iv=0.574))
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = goq.get_quote("NVDA.US", "2026-01-15", 185.0, "PUT", quiet=True)
            self.assertTrue(r["days_to_expiry"] <= 0)
            self.assertEqual(r["greeks"]["theta"], 0.0)
            self.assertEqual(r["theta_source"], "dead_zero")
        finally:
            _restore(orig)

    def test_full_bs_fallback_sets_theta_source(self):
        """原生整体失败走全套 BS 时,theta_source 同步标注 black_scholes。"""
        def raising_metrics(syms):
            raise common.LongbridgeCliError("endpoint down")

        chain = [{"strike": "185", "call_iv": "0.55", "put_iv": "0.574",
                  "call_last": "5", "put_last": "14"}]
        orig = _patch_quote(raising_metrics, chain=chain)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = goq.get_quote("NVDA.US", "2027-01-15", 185.0, "PUT", quiet=True)
            self.assertEqual(r["greeks_source"], "black_scholes")
            self.assertEqual(r["theta_source"], "black_scholes")
            expected = common.bs_greeks(
                178.67, 185.0, common.days_to_years("2027-01-15"),
                0.045, 0.574, "P")["theta"]
            self.assertEqual(r["greeks"]["theta"], expected)
        finally:
            _restore(orig)


class TestChainDuplicateZeroRow(unittest.TestCase):
    """chain 同一 strike 返回"零值行+真实行"重复时,必须取真实行,不被零值行抢占。"""

    def test_zero_row_first_real_row_second(self):
        chain = [
            {"strike": 185, "call_last": 0, "call_iv": 0.0, "call_vol": 0,
             "put_last": 0, "put_iv": 0.0, "put_vol": 0, "standard": "true"},
            {"strike": 185, "call_last": 8.4, "call_iv": 0.577, "call_vol": 2257,
             "put_last": 14.0, "put_iv": 0.574, "put_vol": 1323, "standard": "true"},
        ]
        orig = _patch_quote(lambda sym: {}, chain=chain)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = goq.get_quote("NVDA.US", "2027-01-15", 185.0, "PUT", quiet=True)
            # calc-index 不可用(空 metrics)→ 全套 BS;IV 必须来自真实行 0.574
            self.assertEqual(r["greeks_source"], "black_scholes")
            self.assertEqual(r["implied_volatility"], 0.574)
            self.assertEqual(r["last"], 14.0)
        finally:
            _restore(orig)

    def test_only_zero_row_keeps_zero_iv(self):
        """整条链只有零值行时如实保留(IV 无数据),不伪造。"""
        chain = [{"strike": 185, "call_last": 0, "call_iv": 0.0, "call_vol": 0,
                  "put_last": 0, "put_iv": 0.0, "put_vol": 0, "standard": "true"}]
        orig = _patch_quote(lambda sym: {}, chain=chain)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r = goq.get_quote("NVDA.US", "2027-01-15", 185.0, "PUT", quiet=True)
            # 既有契约:原始 iv 如实保留 0.0,展示层 iv_pct 才折叠为 None
            self.assertEqual(r["implied_volatility"], 0.0)
            self.assertIsNone(r["iv_pct"])
            self.assertIsNone(r["greeks_source"])
        finally:
            _restore(orig)


class TestPortfolioGreeksThetaPropagation(unittest.TestCase):
    """组合 Greeks 逐腿调 get_quote:补算后的 theta 必须传导到加权合计。"""

    def test_portfolio_uses_backfilled_theta(self):
        import calc_option_greeks as cog
        orig_q = cog.get_quote
        try:
            cog.get_quote = lambda ul, expiry, strike, ot, rate=0.045, output_json=False, quiet=True: {
                "greeks": {"delta": -0.552, "gamma": 0.015, "theta": -0.2024,
                           "vega": 0.186, "rho": -0.078},
                "greeks_source": "native", "theta_source": "bs_backfill",
                "iv_pct": 57.4,
            }
            r = cog.calc_portfolio_greeks([
                {"underlying": "NVDA.US", "expiry": "2027-01-15",
                 "strike": 185, "type": "PUT", "action": "SELL", "quantity": 1},
            ])
            # SELL 1 腿 ×100 合约乘数:theta = -0.2024 × (-1) × 100 = +20.24
            self.assertEqual(r["portfolio_greeks"]["theta"], 20.24)
        finally:
            cog.get_quote = orig_q


if __name__ == "__main__":
    unittest.main()
