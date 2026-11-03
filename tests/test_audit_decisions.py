import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ('scripts', 'scripts/decision', 'scripts/technical')]

import analyze_buy_sell as dashboard
import calc_indicators as technical
import calc_relative_strength as strength
import check_entry_rules as entry
import run_quant_indicator as quant
from tests import test_entry_rules_v050 as fixtures


class AuditDecisions(unittest.TestCase):
    def test_offline_demo_respects_json_output(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            entry._demo(output_json=True)
        result = json.loads(output.getvalue())
        self.assertEqual(len(result), 3)
        self.assertTrue(all('verdict' in scene for scene in result.values()))

    def test_event_only_does_not_issue_direction(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(dashboard, 'get_underlying_price', return_value=None))
            for name in ('technical', 'valuation', 'capital', 'options', 'analyst'):
                stack.enter_context(patch.object(dashboard, '_dim_' + name, return_value=(None, 'missing')))
            stack.enter_context(patch.object(dashboard, '_dim_event', return_value=(90, 'far')))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            result = dashboard.analyze('TEST.US')
        self.assertIsNone(result['composite_score'])

    def test_entry_uses_live_price(self):
        bars = fixtures.TestBuySetups()._b1_bars()
        args = SimpleNamespace(lookback=60, max_stop_pct=8, sector_top_decline='no',
                               recent_stopout='no', familiar='yes', prepost_move='no',
                               sector_breakout='no', earnings_days=20, no_heat=True,
                               now='2026-11-03 10:00', output_json=True)
        with patch.object(entry, 'get_kline_adjusted', return_value=bars), \
             patch.object(entry, 'get_underlying_price', return_value=115), \
             patch.object(entry, '_closed_dates', return_value=set()), \
             contextlib.redirect_stdout(io.StringIO()):
            result = entry.analyze('TEST.US', args)
        self.assertEqual(result['rules']['D5']['status'], 'triggered')

    def test_rr_rounding_does_not_pass_gate(self):
        bars = fixtures.TestBuySetups()._b1_bars()
        bars[10] = entry._bar(117, 117, h=119.96)
        bars[35] = entry._bar(103, 103, h=103.5, lo=100)
        # Isolate price levels while exercising feature calculation and gate.
        with patch.object(entry, 'cluster_levels', return_value=[
            {'price': 100, 'touches': 2, 'last_idx': 10},
            {'price': 119.96, 'touches': 2, 'last_idx': 20},
        ]):
            bars[-1] = entry._bar(109, 110)
            result = entry.check_rules(entry.build_features(bars))
        self.assertEqual(result['gate']['status'], 'fail')

    def test_unconfirmed_gate_cannot_pass(self):
        result = entry.check_rules(entry.build_features(fixtures.TestBuySetups()._b1_bars()))
        self.assertEqual(result['gate']['status'], 'manual')
        self.assertNotIn('纪律通过', result['verdict'])

    def test_previous_day_stock_cannot_use_current_sector(self):
        bars = [entry._bar(99, 100) for _ in range(36)]
        bars.extend([entry._bar(100, 106, h=106.2, vol=3000000),
                     entry._bar(106, 105, h=106.2)])
        result = entry._check_b8(entry.build_features(bars), {'sector_breakout': 'yes',
                                  'sector_auto': True, 'sector_date': date(2026, 11, 3)})
        self.assertNotEqual(result['status'], 'matched')

    def test_prior_high_breakout(self):
        bars = [entry._bar(p - .5, p, h=p + .5, lo=p - 1, vol=10) for p in range(70, 101)]
        with patch.object(technical, 'get_kline_adjusted', return_value=bars):
            result = technical.compute_all('TEST.US')
        self.assertTrue(any('20日新高' in signal.replace(' ', '') for signal in result['signals']))

    def test_missing_dates_cannot_make_relative_strength(self):
        with patch.object(strength, 'get_kline_adjusted',
                          return_value=[{'close': 100 + n} for n in range(40)]):
            with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
                strength.analyze('TEST.US', 'BASE.US')

    def test_zero_beta_is_valid(self):
        def bars(symbol, **kwargs):
            return [{'time': str(date(2026, 1, 1) + timedelta(days=n)),
                     'close': 100 if symbol == 'TEST.US' else 100 + n % 2} for n in range(40)]
        with patch.object(strength, 'get_kline_adjusted', side_effect=bars), \
             contextlib.redirect_stdout(io.StringIO()):
            result = strength.analyze('TEST.US', 'BASE.US')
        self.assertEqual(result['beta'], 0)

    def test_quant_historical_cross_check_is_explicit_and_dates_valid(self):
        with patch.object(quant, 'run_quant_script', return_value=''), \
             contextlib.redirect_stdout(io.StringIO()):
            result = quant.fetch_quant_indicator('TEST.US', end='2020-01-01',
                                                cross_check=True, output_json=True)
        self.assertLess(result['start'], result['end'])
        self.assertEqual(result['cross_check']['status'], 'skipped')

    def test_valid_zero_atr_and_unavailable_mfi(self):
        bars = [entry._bar(100, 100, h=100, lo=100, vol=0) for _ in range(60)]
        with patch.object(technical, 'get_kline_adjusted', return_value=bars):
            result = technical.compute_all('TEST.US')
        self.assertEqual(result['atr_pct'], 0)
        self.assertIsNone(result['mfi14'])

    def test_missing_entry_volume_is_not_shrinkage(self):
        bars = [entry._bar(p + .1, p, vol=100) for p in range(130, 100, -1)]
        bars.append(entry._bar(101, 102, vol=None))
        result = entry.check_rules(entry.build_features(bars))
        self.assertNotEqual(result['rules']['D4']['status'], 'triggered')

    def test_missing_technical_volume_keeps_price_history(self):
        bars = [entry._bar(p - .5, p, vol=10) for p in range(70, 102)]
        bars[-1]["volume"] = None
        with patch.object(technical, "get_kline_adjusted", return_value=bars):
            result = technical.compute_all("TEST.US")
        self.assertEqual(result["price"], 101)
        self.assertIsNone(result["volume_ratio"])
        self.assertIsNone(result["mfi14"])

    def test_matched_structure_can_pass_with_confirmed_gate(self):
        result = entry.check_rules(entry.build_features(fixtures.TestBuySetups()._b1_bars()), {
            "target_price": 110, "sector_top_decline": "no", "recent_stopout": "no",
            "familiar": "yes", "prepost_move": "no", "earnings_days": 20,
            "now": entry.datetime(2026, 11, 3, 10), "market": "US",
        })
        self.assertEqual(result["gate"]["status"], "pass")
        self.assertEqual(result["required_confirmations"], [])
        self.assertIn("纪律通过", result["verdict"])

    def test_explicit_zero_stop_limit_is_respected(self):
        result = entry.check_rules(entry.build_features(fixtures.TestBuySetups()._b1_bars()),
                                   {"max_stop_pct": 0})
        self.assertEqual(result["rules"]["D5"]["status"], "triggered")

    def test_stock_and_sector_can_match_on_same_day(self):
        bars = [entry._bar(99, 100) for _ in range(36)]
        bars.append(dict(entry._bar(100, 106, h=106.2, vol=3000000), date="2026-11-03"))
        result = entry._check_b8(entry.build_features(bars), {"sector_breakout": "yes",
                                  "sector_auto": True, "sector_date": date(2026, 11, 3)})
        self.assertEqual(result["status"], "matched")

    def test_relative_strength_normalizes_and_deduplicates_dates(self):
        rows = [{"date": "2026/11/03", "close": 3}, {"date": "2026-11-03", "close": 3},
                {"date": "2026-11-02", "close": 2}, {"date": "2026-11-02", "close": 4}]
        self.assertEqual(strength._dated_closes(rows, "TEST.US"), {date(2026, 11, 3): 3})

    def test_custom_strategy_file_uses_backtest_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "strategy.pine"
            path.write_text('//@version=5\nstrategy ("Test")\n', encoding="utf-8")
            with patch.object(quant, "run_quant_script", return_value={}) as run, \
                 contextlib.redirect_stdout(io.StringIO()):
                result = quant.fetch_quant_indicator("TEST.US", preset="custom", script_file=str(path),
                                                    end="2020-01-01", output_json=True)
        self.assertEqual(result["mode"], "backtest")
        self.assertFalse(run.call_args.kwargs.get("raw", False))

    def test_missing_funds_differ_from_balanced_funds(self):
        with patch.object(dashboard, "get_short_trades", return_value={}), \
             patch.object(dashboard, "get_capital_flow_snapshot", return_value={}) as funds:
            self.assertIsNone(dashboard._dim_capital("TEST.US", [], [])[0])
            funds.return_value = {"net": {"large": 0}, "capital_in": {"large": 10},
                                  "capital_out": {"large": 10}}
            self.assertEqual(dashboard._dim_capital("TEST.US", [], [])[0], 50)

    def test_event_risk_weakens_bullish_evidence_only(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(dashboard, "get_underlying_price", return_value=None))
            dims = {}
            for name in ("technical", "valuation", "capital", "options", "analyst"):
                dims[name] = stack.enter_context(patch.object(
                    dashboard, "_dim_" + name, return_value=(80, "directional data")
                ))
            stack.enter_context(patch.object(dashboard, "_dim_event", return_value=(7, "near")))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            result = dashboard.analyze("TEST.US")
            self.assertEqual(result["coverage_weight"], 90)
            self.assertEqual(result["composite_score"], 73)
            for dim in dims.values():
                dim.return_value = (40, "directional data")
            self.assertEqual(dashboard.analyze("TEST.US")["composite_score"], 40)
            dims["technical"].return_value = (None, "missing")
            self.assertIsNone(dashboard.analyze("TEST.US")["composite_score"])
    def test_text_indicators_render_zero_and_unavailable(self):
        for count, price in ((60, 100), (30, 100), (30, 0)):
            with self.subTest(count=count, price=price):
                bars = [entry._bar(price, price, h=price, lo=price, vol=0) for _ in range(count)]
                with patch.object(technical, "get_kline_adjusted", return_value=bars), \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    result = technical.show_indicators("TEST.US")
                self.assertIsNone(result["obv"]["obv"])
                self.assertIn("N/A", output.getvalue())
                if price:
                    self.assertIn("0.0%", output.getvalue())

    def test_complete_structure_with_missing_volume_cannot_pass(self):
        path = [50 * 1.01 ** i for i in range(55)]
        bars = fixtures.gen(path)
        prior_ma5 = sum(path[-5:]) / 5
        bars.append(entry._bar(path[-1], path[-1] * .995, h=path[-1] * 1.002,
                               lo=prior_ma5 * .998, vol=None))
        result = entry.check_rules(entry.build_features(bars), self._confirmed_entry_options())
        self.assertIn("B5", result["matched"])
        self.assertIn("volume", result["required_confirmations"])
        self.assertNotIn("纪律通过", result["verdict"])

    def test_complete_structure_with_quote_fallback_cannot_pass(self):
        bars = fixtures.TestBuySetups()._b1_bars()
        args = SimpleNamespace(lookback=60, max_stop_pct=8, sector_top_decline="no",
                               recent_stopout="no", familiar="yes", prepost_move="no",
                               sector_breakout="no", earnings_days=20, no_heat=True,
                               now="2026-11-03 10:00", target_price=110, output_json=True)
        with patch.object(entry, "get_kline_adjusted", return_value=bars), \
             patch.object(entry, "get_underlying_price", return_value=None), \
             patch.object(entry, "_closed_dates", return_value=set()), \
             contextlib.redirect_stdout(io.StringIO()):
            result = entry.analyze("TEST.US", args)
        self.assertIn("B1", result["matched"])
        self.assertEqual(result["price_source"], "last_daily_close")
        self.assertIn("quote", result["required_confirmations"])
        self.assertNotIn("纪律通过", result["verdict"])

    @staticmethod
    def _confirmed_entry_options():
        return {
            "target_price": 110, "sector_top_decline": "no", "recent_stopout": "no",
            "familiar": "yes", "prepost_move": "no", "earnings_days": 20,
            "now": entry.datetime(2026, 11, 3, 10), "market": "US",
        }
