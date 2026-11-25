"""v0.7.0 PR-3 单元测试：期权卖方策略 / 目标 Delta 选腿 / 内联损益 / 流动性校验 + IV 自动采集与冷启动代理。"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
for _sub in ("", "quote", "decision", "market", "technical", "fundamental", "calendar", "sentiment"):
    p = str(_SCRIPTS / _sub if _sub else _SCRIPTS)
    if p not in sys.path:
        sys.path.insert(0, p)

import common  # noqa: E402
import calc_iv_percentile as pct_mod  # noqa: E402
import calc_iv_rank as rank_mod  # noqa: E402
import calc_option_pnl as pnl_mod  # noqa: E402
import get_iv_history as iv_hist  # noqa: E402
import get_option_strategy as strat_mod  # noqa: E402


def _synthetic_chain(spot: float = 100.0, expiry_days: int = 30, rate: float = 0.045, iv: float = 0.25) -> list[dict]:
    T = expiry_days / 365.0
    rows = []
    for k in range(80, 125, 5):
        call_iv = iv + max(0.0, (k - spot) * 0.001)
        put_iv = iv + max(0.0, (spot - k) * 0.002)
        c_px = common.bs_price(spot, float(k), T, rate, call_iv, "C")
        p_px = common.bs_price(spot, float(k), T, rate, put_iv, "P")
        rows.append({
            "strike": float(k),
            "call_iv": call_iv,
            "put_iv": put_iv,
            "call_last": round(max(c_px, 0.05), 2),
            "put_last": round(max(p_px, 0.05), 2),
            "call_vol": 150 if 90 <= k <= 115 else 0,
            "put_vol": 180 if 85 <= k <= 110 else 0,
            "standard": True,
        })
    return rows


def _make_bars(n: int = 290) -> list[dict]:
    """构造波动率逐段变化的正股日线序列，保证 rolling HV30 区间非退化。"""
    bars = []
    px = 100.0
    for i in range(n):
        amp = 0.006 if (i // 35) % 2 == 0 else 0.022
        ret = amp if (i % 2 == 0) else -amp * 0.85
        px = px * math.exp(ret)
        bars.append({
            "open": round(px * 0.998, 2),
            "high": round(px * 1.005, 2),
            "low": round(px * 0.995, 2),
            "close": round(px, 2),
            "volume": 1000000,
            "time": f"2026-01-{(i % 28) + 1:02d}T16:00:00Z",
        })
    return bars


class TestOptionSellerStrategiesV070(unittest.TestCase):
    def setUp(self):
        buf = io.StringIO()
        ctx = contextlib.redirect_stdout(buf)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def test_seller_strategies_and_inline_pnl(self):
        spot = 100.0
        expiry = "2027-02-19"
        chain = _synthetic_chain(spot=spot, expiry_days=30, iv=0.28)
        with patch.object(strat_mod, "get_underlying_price", return_value=spot), \
             patch.object(strat_mod, "get_option_chain", return_value=chain), \
             patch.object(strat_mod, "days_to_years", return_value=30 / 365.0):

            bps = strat_mod.build_strategy(
                "AAPL.US", expiry, "BULL_PUT_SPREAD",
                target_delta=0.20, width=5.0, with_pnl=True,
            )
            self.assertEqual(bps["strategy"], "BULL_PUT_SPREAD")
            self.assertEqual(bps["selection_mode"], "delta")
            self.assertEqual(len(bps["legs"]), 2)
            sell_leg, buy_leg = bps["legs"]
            self.assertEqual((sell_leg["action"], sell_leg["type"]), ("SELL", "PUT"))
            self.assertEqual((buy_leg["action"], buy_leg["type"]), ("BUY", "PUT"))
            self.assertLess(buy_leg["strike"], sell_leg["strike"])
            self.assertLess(sell_leg["strike"], spot)
            self.assertEqual(round(sell_leg["strike"] - buy_leg["strike"], 2), 5.0)
            self.assertTrue(bps["pnl_summary"]["net_credit"])
            self.assertGreater(bps["pnl_summary"]["pop_bs_pct"], 50.0)
            self.assertGreater(bps["pnl_summary"]["return_on_risk_pct"], 0.0)
            self.assertGreater(bps["bs_portfolio_greeks"]["delta"], 0.0)
            self.assertGreater(bps["bs_portfolio_greeks"]["theta"], 0.0)

            bcs = strat_mod.build_strategy(
                "AAPL.US", expiry, "BEAR_CALL_SPREAD",
                target_delta=0.20, width=5.0, with_pnl=True,
            )
            c_sell, c_buy = bcs["legs"]
            self.assertEqual((c_sell["action"], c_sell["type"]), ("SELL", "CALL"))
            self.assertEqual((c_buy["action"], c_buy["type"]), ("BUY", "CALL"))
            self.assertLess(spot, c_sell["strike"])
            self.assertLess(c_sell["strike"], c_buy["strike"])
            self.assertTrue(bcs["pnl_summary"]["net_credit"])
            self.assertLess(bcs["bs_portfolio_greeks"]["delta"], 0.0)
            self.assertGreater(bcs["bs_portfolio_greeks"]["theta"], 0.0)

            ic = strat_mod.build_strategy(
                "AAPL.US", expiry, "IRON_CONDOR",
                target_delta=0.20, width=5.0, with_pnl=True,
            )
            self.assertEqual(len(ic["legs"]), 4)
            lp, sp, sc, lc = ic["legs"]
            self.assertEqual([(x["action"], x["type"]) for x in ic["legs"]], [
                ("BUY", "PUT"), ("SELL", "PUT"), ("SELL", "CALL"), ("BUY", "CALL")
            ])
            self.assertLess(lp["strike"], sp["strike"])
            self.assertLess(sp["strike"], spot)
            self.assertLess(spot, sc["strike"])
            self.assertLess(sc["strike"], lc["strike"])
            self.assertTrue(ic["pnl_summary"]["net_credit"])
            self.assertEqual(len(ic["pnl_summary"]["break_even_points"]), 2)
            be_lo, be_hi = ic["pnl_summary"]["break_even_points"]
            self.assertLess(sp["strike"] - 5.0, be_lo)
            self.assertLess(be_lo, sp["strike"])
            self.assertLess(sc["strike"], be_hi)
            self.assertLess(be_hi, sc["strike"] + 5.0)
            self.assertGreater(ic["pnl_summary"]["pop_bs_pct"], 40.0)

    def test_delta_validation_and_missing_iv_errors(self):
        chain = _synthetic_chain(spot=100.0)
        with patch.object(strat_mod, "get_underlying_price", return_value=100.0), \
             patch.object(strat_mod, "get_option_chain", return_value=chain), \
             patch.object(strat_mod, "days_to_years", return_value=30 / 365.0):
            with self.assertRaisesRegex(ValueError, "目标 Delta"):
                strat_mod.build_strategy("AAPL.US", "2027-02-19", "BULL_PUT_SPREAD", target_delta=0.01)
            with self.assertRaisesRegex(ValueError, "目标 Delta"):
                strat_mod.build_strategy("AAPL.US", "2027-02-19", "BULL_PUT_SPREAD", target_delta=0.60)
            with self.assertRaisesRegex(ValueError, "width"):
                strat_mod.build_strategy("AAPL.US", "2027-02-19", "BULL_PUT_SPREAD", width=-5.0)

        with patch.object(strat_mod, "get_underlying_price", return_value=100.0), \
             patch.object(strat_mod, "get_option_chain", return_value=chain), \
             patch.object(strat_mod, "days_to_years", return_value=0.0):
            with self.assertRaisesRegex(ValueError, "已过期"):
                strat_mod.build_strategy("AAPL.US", "2026-11-20", "BULL_PUT_SPREAD", target_delta=0.20)

        put_only_chain = [dict(r, call_iv=None) for r in chain]
        with patch.object(strat_mod, "get_underlying_price", return_value=100.0), \
             patch.object(strat_mod, "get_option_chain", return_value=put_only_chain), \
             patch.object(strat_mod, "days_to_years", return_value=30 / 365.0):
            res = strat_mod.build_strategy("AAPL.US", "2027-02-19", "BULL_PUT_SPREAD", target_delta=0.20)
            self.assertEqual(len(res["legs"]), 2)
            with self.assertRaisesRegex(ValueError, "OTM Call"):
                strat_mod.build_strategy("AAPL.US", "2027-02-19", "IRON_CONDOR", target_delta=0.20)

    def test_liquidity_check_flags_low_oi_and_passes_liquid(self):
        chain = _synthetic_chain(spot=100.0)
        low_oi_metrics = {
            common.build_lbr_option_symbol("AAPL", "2027-02-19", 95.0, "PUT"): {"oi": 500},
            common.build_lbr_option_symbol("AAPL", "2027-02-19", 90.0, "PUT"): {"oi": 25},
        }
        high_oi_metrics = {
            common.build_lbr_option_symbol("AAPL", "2027-02-19", 95.0, "PUT"): {"oi": 500},
            common.build_lbr_option_symbol("AAPL", "2027-02-19", 90.0, "PUT"): {"oi": 320},
        }
        with patch.object(strat_mod, "get_underlying_price", return_value=100.0), \
             patch.object(strat_mod, "get_option_chain", return_value=chain), \
             patch.object(strat_mod, "days_to_years", return_value=30 / 365.0), \
             patch.object(strat_mod, "get_option_contract_metrics", return_value=low_oi_metrics):
            warn = strat_mod.build_strategy(
                "AAPL.US", "2027-02-19", "BULL_PUT_SPREAD", width=5.0, check_liquidity=True
            )
        self.assertFalse(warn["liquidity"]["passed"])
        self.assertTrue(any("90.0 PUT" in s for s in warn["liquidity"]["low_oi_legs"]))

        with patch.object(strat_mod, "get_underlying_price", return_value=100.0), \
             patch.object(strat_mod, "get_option_chain", return_value=chain), \
             patch.object(strat_mod, "days_to_years", return_value=30 / 365.0), \
             patch.object(strat_mod, "get_option_contract_metrics", return_value=high_oi_metrics):
            ok = strat_mod.build_strategy(
                "AAPL.US", "2027-02-19", "BULL_PUT_SPREAD", width=5.0, check_liquidity=True
            )
        self.assertTrue(ok["liquidity"]["passed"])
        self.assertEqual(ok["liquidity"]["low_oi_legs"], [])

    def test_analyze_pnl_quiet_suppresses_stdout(self):
        chain = [dict(strike=95.0, put_last=2.0), dict(strike=90.0, put_last=0.8)]
        legs = [
            {"underlying": "AAPL.US", "expiry": "2027-02-19", "strike": 95.0, "type": "PUT", "action": "SELL", "quantity": 1},
            {"underlying": "AAPL.US", "expiry": "2027-02-19", "strike": 90.0, "type": "PUT", "action": "BUY", "quantity": 1},
        ]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = pnl_mod.analyze_pnl(legs, quiet=True, underlying_price=100.0, chain=chain)
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(res["total_cost"], -120.0)


class TestIVAutoCaptureAndColdStartV070(unittest.TestCase):
    def setUp(self):
        buf = io.StringIO()
        ctx = contextlib.redirect_stdout(buf)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def test_unittest_guard_skips_when_dir_not_overridden(self):
        with patch.dict(os.environ, {"LBR_IV_HISTORY_DIR": "", "LBR_AUTO_IV_RECORD": "1"}, clear=False):
            self.assertFalse(iv_hist.maybe_record_daily_iv("AAPL.US"))

    def test_opportunistic_auto_capture_writes_and_skips_same_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_now = datetime(2026, 11, 25, 11, 0, tzinfo=timezone(timedelta(hours=-5)))
            calls = []

            def _fake_iv(sym):
                calls.append(sym)
                return 0.275, {"tenor_days": 30, "source_expiries": [{"expiry": "2026-12-18", "days": 23.0, "strike": 100.0, "iv": 0.275}]}

            with patch.dict(os.environ, {"LBR_IV_HISTORY_DIR": tmp, "LBR_AUTO_IV_RECORD": "1"}, clear=False), \
                 patch.object(iv_hist, "market_now", return_value=fake_now), \
                 patch.object(iv_hist, "get_current_atm_iv", side_effect=_fake_iv):
                first = iv_hist.maybe_record_daily_iv("AAPL.US")
                second = iv_hist.maybe_record_daily_iv("AAPL.US")
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(len(calls), 1)

            saved_path = Path(tmp) / "AAPL_US.json"
            self.assertTrue(saved_path.is_file())
            rows = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["date"], "2026-11-25")
            self.assertEqual(rows[0]["atm_iv_pct"], 27.5)
            self.assertEqual(rows[0]["tenor_days"], 30)

            with patch.dict(os.environ, {"LBR_IV_HISTORY_DIR": tmp, "LBR_AUTO_IV_RECORD": "0"}, clear=False), \
                 patch.object(iv_hist, "market_now", return_value=fake_now), \
                 patch.object(iv_hist, "get_current_atm_iv", side_effect=_fake_iv):
                self.assertFalse(iv_hist.maybe_record_daily_iv("MSFT.US"))
            self.assertFalse(iv_hist.maybe_record_daily_iv("700.HK"))
            self.assertFalse(iv_hist.maybe_record_daily_iv(".VIX.US"))

    def test_resolve_and_batch_iv_history_resilient(self):
        watchlist = [
            {"id": 1, "name": "Tech", "securities": [
                {"symbol": "AAPL.US"}, {"symbol": "700.HK"}, {"symbol": "NVDA.US"},
            ]},
        ]
        positions = [{"symbol": "msft.us"}, {"symbol": "AAPL261218C350000.US"}]
        with patch.object(iv_hist, "get_watchlist_groups", return_value=watchlist), \
             patch.object(iv_hist, "get_stock_positions", return_value=positions):
            us, skipped = iv_hist.resolve_iv_symbols(
                ["AAPL.US", ".VIX.US"], use_watchlist=True, use_positions=True
            )
        self.assertEqual([s.upper() for s in us], ["AAPL.US", "NVDA.US", "MSFT.US"])
        self.assertEqual(skipped, [".VIX.US", "700.HK", "AAPL261218C350000.US"])

        def _fake_hist(sym, append=True, output_json=False, quiet=False):
            if sym == "BAD.US":
                raise RuntimeError("no option chain")
            return {
                "symbol": sym,
                "comparable_points": 2,
                "data_points": 2,
                "appended_today": True,
                "date_range": "2026-11-24 ~ 2026-11-25",
                "history_file": f"/tmp/{sym}.json",
                "series": [
                    {"date": "2026-11-24", "atm_iv_pct": 24.0, "tenor_days": 30},
                    {"date": "2026-11-25", "atm_iv_pct": 26.5, "tenor_days": 30},
                ],
            }

        with patch.object(iv_hist, "get_batch_quotes", return_value={}), \
             patch.object(iv_hist, "iv_history", side_effect=_fake_hist):
            batch = iv_hist.batch_iv_history(["AAPL.US", "BAD.US"], skipped=["700.HK"])
        self.assertEqual(batch["succeeded"], 1)
        self.assertEqual(batch["failed"], 1)
        self.assertEqual(batch["results"][0]["delta_iv_pct"], 2.5)
        self.assertFalse(batch["results"][1]["ok"])

    def test_iv_rank_and_percentile_cold_start_proxy_and_strict(self):
        snap_1pt = {
            "appended_today": True,
            "observed_at": "2026-11-25T11:00:00-05:00",
            "date_range": "2026-11-25 ~ 2026-11-25",
            "series": [{
                "date": "2026-11-25",
                "atm_iv_pct": 30.0,
                "tenor_days": 30,
                "observed_at": "2026-11-25T11:00:00-05:00",
            }],
        }
        bars = _make_bars(290)
        with patch.object(rank_mod, "_build_series", return_value=snap_1pt), \
             patch.object(rank_mod, "get_kline_adjusted", return_value=bars):
            rk = rank_mod.calc_iv_rank("AAPL.US", min_points=20)
            with self.assertRaisesRegex(ValueError, "历史 IV 数据不足"):
                rank_mod.calc_iv_rank("AAPL.US", min_points=20, allow_proxy=False)

        self.assertIsNone(rk["iv_rank"])
        self.assertEqual(rk["rank_basis"], "hv_52w_proxy")
        self.assertIsNotNone(rk["hv_proxy_rank"])
        self.assertGreaterEqual(rk["hv_proxy_rank"], 0.0)
        self.assertLessEqual(rk["hv_proxy_rank"], 100.0)
        self.assertAlmostEqual(
            rk["hv_proxy"]["vrp_pct"],
            round(30.0 - rk["hv_proxy"]["hv_current_pct"], 2),
            places=2,
        )

        with patch.object(pct_mod, "_build_series", return_value=snap_1pt), \
             patch.object(pct_mod, "get_kline_adjusted", return_value=bars):
            pc = pct_mod.calc_iv_percentile("AAPL.US", min_points=20)
            with self.assertRaisesRegex(ValueError, "历史 IV 数据不足"):
                pct_mod.calc_iv_percentile("AAPL.US", min_points=20, allow_proxy=False)

        self.assertIsNone(pc["iv_percentile"])
        self.assertEqual(pc["rank_basis"], "hv_52w_proxy")
        self.assertIsNotNone(pc["hv_proxy_percentile"])

    def test_full_iv_rank_restored_and_gap_continuity_warning(self):
        # 构造 20 天记录，最后两条相隔 25 天以触发断档提醒
        series = [
            {"date": f"2026-10-{d:02d}", "atm_iv_pct": 20.0 + d, "tenor_days": 30}
            for d in range(1, 20)
        ] + [
            {"date": "2026-11-25", "atm_iv_pct": 35.0, "tenor_days": 30,
             "observed_at": "2026-11-25T11:00:00-05:00"}
        ]
        snap = {
            "appended_today": True,
            "observed_at": "2026-11-25T11:00:00-05:00",
            "date_range": "2026-10-01 ~ 2026-11-25",
            "series": series,
        }
        bars = _make_bars(290)
        with patch.object(rank_mod, "_build_series", return_value=snap), \
             patch.object(rank_mod, "get_kline_adjusted", return_value=bars):
            rk = rank_mod.calc_iv_rank("AAPL.US", min_points=20)
        self.assertEqual(rk["rank_basis"], "iv_history")
        self.assertIsNotNone(rk["iv_rank"])
        self.assertIsNotNone(rk["coverage_warning"])
        self.assertIn("断档", rk["coverage_warning"])
        self.assertIn("hv_proxy", rk)


if __name__ == "__main__":
    unittest.main()
