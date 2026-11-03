import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "quote"))

import calc_expected_move as em
import calc_gamma_profile as gamma
import calc_iv_percentile as percentile
import calc_iv_rank as rank
import calc_max_pain as pain
import calc_option_pnl as pnl
import get_option_strategy as strategy
import get_iv_history as history


class OptionAuditTests(unittest.TestCase):
    def setUp(self):
        redirect = contextlib.redirect_stdout(io.StringIO())
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def test_pnl_solves_beyond_plot_and_classifies_bounds(self):
        base = dict(underlying="X.US", expiry="2027-01-01", type="CALL")
        chain = [dict(strike=100, call_last=5), dict(strike=110, call_last=2),
                 dict(strike=150, call_last=2)]
        with patch.object(pnl, "get_underlying_price", return_value=100), patch.object(
                pnl, "get_option_chain", return_value=chain):
            spread = pnl.analyze_pnl([dict(base, strike=100),
                                      dict(base, strike=110, action="SELL")])
            far_call = pnl.analyze_pnl([dict(base, strike=150)])
        self.assertEqual(spread["max_profit"], "700.0 (有限)")
        self.assertEqual(spread["max_loss"], "-300.0 (有限)")
        self.assertEqual(far_call["break_even_points"], [152.0])
        self.assertIn("未封顶", far_call["max_profit"])
        self.assertEqual(far_call["max_loss"], "-200.0 (有限)")

    def test_gamma_uses_actual_sign_above_downward_flip(self):
        legs = [dict(strike=90, iv=.2, oi=100, T=.1, side="C"),
                dict(strike=110, iv=.2, oi=100, T=.1, side="P")]
        with patch.object(gamma, "_collect_legs", return_value=(legs, 105, ["2027-01-01"])):
            result = gamma.analyze("X.US")
        self.assertLess(result["total_gex_at_spot"], 0)
        self.assertIn("负 GEX", result["regime"])
        self.assertNotIn("正 GEX 区", result["regime"])

    def test_expected_move_keeps_straddle_and_iv_bands_separate(self):
        chain = [dict(strike=99, call_last=9, put_last=7, call_iv=.2)]
        with patch.object(em, "get_underlying_price", return_value=100), patch.object(
                em, "get_option_chain", return_value=chain), patch.object(
                em, "days_to_years", return_value=1):
            result = em.analyze("X.US", date="2027-01-01")
        self.assertNotIn("68%", result["note"])
        self.assertEqual(result["main"]["straddle_break_even_low"], 83)
        self.assertEqual(result["main"]["iv_range_low"], 80)

    def test_max_pain_scales_standard_payout_and_excludes_adjusted_chain(self):
        chain = [dict(strike=90, call_vol=10), dict(strike=100, put_vol=20),
                 dict(strike=120, put_vol=10000, standard=False)]
        with patch.object(pain, "get_underlying_price", return_value=100), patch.object(
                pain, "get_chain_oi", return_value={"oi_mode": False}), patch.object(
                pain, "get_option_chain", return_value=chain):
            result = pain.analyze("X.US", date="2027-01-01")
        self.assertEqual(result["max_pain"], 100)
        self.assertEqual(result["total_payout_at_max_pain"], 10000)

    def test_spread_cannot_select_same_strike_for_both_legs(self):
        chain = [dict(strike=k) for k in [90, 100, 110]]
        with patch.object(strategy, "get_underlying_price", return_value=100), patch.object(
                strategy, "get_option_chain", return_value=chain):
            result = strategy.build_strategy("X.US", "2027-01-01", "BULL_CALL_SPREAD", .01)
        self.assertEqual([leg["strike"] for leg in result["legs"]], [100, 110])

    def test_rank_and_percentile_reject_stale_history(self):
        snapshot = dict(series=[dict(atm_iv_pct=20), dict(atm_iv_pct=40)],
                        date_range="2025-01-01 ~ 2025-01-02", appended_today=False)
        for mod, func in [(rank, rank.calc_iv_rank), (percentile, percentile.calc_iv_percentile)]:
            with self.subTest(func=func.__name__), patch.object(
                    mod, "_build_series", return_value=snapshot):
                with self.assertRaisesRegex(ValueError, "当前"):
                    func("X.US", min_points=2)

    def test_iv_sample_interpolates_total_variance_to_30_days(self):
        expiries = ["2027-01-18", "2027-01-28"]
        def chain(symbol, expiry):
            return [dict(strike=100, call_iv=.2 if expiry == expiries[0] else .4)]
        with patch.object(history, "get_option_expirations", return_value=expiries), patch.object(
                history, "get_underlying_price", return_value=100), patch.object(
                history, "get_option_chain", side_effect=chain), patch.object(
                history, "days_to_years", create=True, side_effect=[25/365, 35/365]):
            iv, meta = history.get_current_atm_iv("X.US")
        self.assertAlmostEqual(iv, ((.2**2*25 + .4**2*35)/60)**.5)
        self.assertEqual(meta["tenor_days"], 30)

    def test_gamma_zero_without_sign_change_is_not_flip(self):
        def gex(legs, spot, rate):
            return (spot - 100) ** 2
        with patch.object(gamma, "_gex_at", side_effect=gex):
            flip, _ = gamma._find_flip([], 100, .045, .2)
        self.assertIsNone(flip)

    def test_crush_uses_comparable_consecutive_calendar_samples(self):
        import analyze_iv_crush as crush

        series = [dict(date="2026-11-01", atm_iv_pct=80, tenor_days=30),
                  dict(date="2026-11-05", atm_iv_pct=60, tenor_days=30),
                  dict(date="2026-11-06", atm_iv_pct=40, tenor_days=30)]
        with patch.object(crush, "find_next_earnings", return_value=None), patch.object(
                crush, "_get_current_iv", return_value=.4), patch.object(
                crush, "_load_iv_history", return_value=series):
            result = crush.analyze_iv_crush("X.US")
        self.assertEqual([x["date"] for x in result["historical_crush_examples"]], ["2026-11-06"])
        self.assertIn("未关联财报", result["note"])

    def test_pnl_closed_form_stock_and_option_strategies(self):
        base = dict(underlying="X.US", expiry="2027-01-01")
        chain = [dict(strike=95, put_last=2), dict(strike=100, call_last=5, put_last=4),
                 dict(strike=110, call_last=3)]
        stock = dict(base, type="STOCK", strike=100)
        put = dict(base, type="PUT", strike=95)
        short_call = dict(base, type="CALL", strike=110, action="SELL")
        straddle = [dict(base, type=kind, strike=100) for kind in ("CALL", "PUT")]
        cases = [
            ("protective put", [stock, put], [102], "未封顶", "-700.0 (有限)"),
            ("covered call", [stock, short_call], [97], "1300.0 (有限)", "-9700.0 (有限)"),
            ("naked short call", [short_call], [113], "300.0 (有限)", "未封顶"),
            ("long straddle", straddle, [91, 109], "未封顶", "-900.0 (有限)"),
        ]
        with patch.object(pnl, "get_underlying_price", return_value=100), patch.object(
                pnl, "get_option_chain", return_value=chain):
            for label, legs, roots, profit, loss in cases:
                with self.subTest(strategy=label):
                    result = pnl.analyze_pnl(legs)
                    self.assertEqual(result["break_even_points"], roots)
                    self.assertEqual(result["max_profit"], profit)
                    self.assertEqual(result["max_loss"], loss)

    def test_pnl_break_even_can_be_a_range(self):
        base = dict(underlying="X.US", expiry="2027-01-01", type="CALL")
        chain = [dict(strike=90, call_last=12), dict(strike=100, call_last=2)]
        with patch.object(pnl, "get_underlying_price", return_value=100), patch.object(
                pnl, "get_option_chain", return_value=chain):
            result = pnl.analyze_pnl([dict(base, strike=90),
                                      dict(base, strike=100, action="SELL")])
        self.assertEqual(result["break_even_ranges"], [[100, None]])

    def test_sparse_chain_rejects_unequal_butterfly_wings(self):
        chain = [dict(strike=k) for k in [90, 100, 105]]
        with patch.object(strategy, "get_underlying_price", return_value=100), patch.object(
                strategy, "get_option_chain", return_value=chain):
            with self.assertRaisesRegex(ValueError, "等宽"):
                strategy.build_strategy("X.US", "2027-01-01", "BUTTERFLY")

    def test_iv_does_not_extrapolate_from_one_side(self):
        with patch.object(history, "get_option_expirations", return_value=["2027-01-18"]), patch.object(
                history, "get_underlying_price", return_value=100), patch.object(
                history, "get_option_chain", return_value=[dict(strike=100, call_iv=.2)]), patch.object(
                history, "days_to_years", return_value=25/365):
            self.assertEqual(history.get_current_atm_iv("X.US"), (None, None))

    def test_rank_and_percentile_ignore_legacy_variable_tenor_history(self):
        snapshot = dict(series=[dict(date="2026-10-30", atm_iv_pct=80),
                                dict(date="2026-11-01", atm_iv_pct=20, tenor_days=30),
                                dict(date="2026-11-02", atm_iv_pct=40, tenor_days=30)],
                        date_range="2026-10-30 ~ 2026-11-02", appended_today=True)
        for mod, func, field in [(rank, rank.calc_iv_rank, "iv_rank"),
                                 (percentile, percentile.calc_iv_percentile, "iv_percentile")]:
            with self.subTest(func=func.__name__), patch.object(
                    mod, "_build_series", return_value=snapshot):
                result = func("X.US", min_points=2)
                self.assertEqual(result[field], 100)
                self.assertEqual(result["data_points"], 2)
                self.assertEqual(result["date_range"], "2026-11-01 ~ 2026-11-02")

    def test_iv_rejects_missing_freshness_and_validates_saved_dates(self):
        snapshot = dict(series=[], date_range="")
        with patch.object(rank, "_build_series", return_value=snapshot):
            with self.assertRaisesRegex(ValueError, "当前"):
                rank.calc_iv_rank("X.US")
        records = [
            {"date": "2026-11-02", "atm_iv_pct": 30, "tenor_days": 30},
            {"date": "bad date", "atm_iv_pct": 90, "tenor_days": 30},
            {"date": "2026-11-01", "atm_iv_pct": 20, "tenor_days": 30},
            {"date": "2026-11-03", "atm_iv_pct": "bad", "tenor_days": 30},
            None,
        ]
        self.assertEqual([x["atm_iv_pct"] for x in history.comparable_iv_series(records)], [20, 30])

    def test_portfolio_greeks_rejects_cross_asset_and_invalid_action(self):
        import calc_option_greeks as greeks

        leg = dict(underlying="X.US", expiry="2027-01-01", strike=100, type="STOCK")
        with self.assertRaisesRegex(ValueError, "同标的"):
            greeks.calc_portfolio_greeks([leg, dict(leg, underlying="Y.US", action="SELL")])
        with self.assertRaisesRegex(ValueError, "BUY.*SELL"):
            greeks.calc_portfolio_greeks([dict(leg, action="SEL")])

    def test_gamma_sampled_zero_and_zero_plateau_are_preserved(self):
        import calc_gex as gex

        self.assertEqual(gex._nearest_sign_crossing([90, 100, 110], [-10, 0, 20], 100), 100)
        self.assertEqual(gex._nearest_sign_crossing([90, 100, 105, 110], [-10, 0, 0, 20], 103), 103)
        self.assertIsNone(gex._nearest_sign_crossing([90, 100, 110], [0, 0, 20], 100))

    def test_gamma_scan_expands_to_cap_even_when_intermediate_exceeds_cap(self):
        with patch.object(gamma, "_gex_at", side_effect=lambda legs, spot, rate: spot - 135):
            flip, _ = gamma._find_flip([], 100, .045, .30)
        self.assertEqual(flip, 135)
