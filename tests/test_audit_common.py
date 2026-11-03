"""Independent numerical and schema regressions from the November audit."""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import common


class CommonAuditTests(unittest.TestCase):
    def test_nonfinite_numbers_are_missing(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e999', float('nan'), True):
            with self.subTest(value=value):
                self.assertIsNone(common.to_float(value))
                self.assertIsNone(common.to_int(value))

    def test_normalization_preserves_identifiers_and_unknown_strings(self):
        data = common.normalize_records([{'cusip': '037833100', 'cik': '0001422848',
            'name': '000123', 'date': '20261103', 'unknown': '00123',
            'holdings': [{'code': '00130E100', 'shares': '12', 'price': '1.5'}]}])[0]
        self.assertEqual(data['cusip'], '037833100')
        self.assertEqual(data['cik'], '0001422848')
        self.assertEqual(data['unknown'], '00123')
        self.assertEqual(data['name'], '000123')
        self.assertEqual(data['date'], '20261103')
        self.assertEqual(data['holdings'][0], {'code': '00130E100','shares':12,'price':1.5})

    def test_json_nonfinite_values_become_null(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            common.print_json({'x': float('nan'), 'nested': [float('inf')]})
        data = json.loads(out.getvalue(), parse_constant=lambda x: self.fail(x))
        self.assertEqual(data, {'x': None, 'nested': [None]})

    def test_bs_zero_volatility_preserves_discounting(self):
        self.assertAlmostEqual(common.bs_price(100, 100, 1, .05, 0, 'C'), 4.8770575499)
        g = common.bs_greeks(100, 100, 1, .05, 0, 'C')
        self.assertEqual(g['delta'], 1)
        self.assertAlmostEqual(g['rho'], .9512294245)
        self.assertAlmostEqual(g['theta'], -.01303054006)

    def test_bs_zero_spot_put_and_zero_strike_call(self):
        self.assertAlmostEqual(common.bs_price(0, 100, 1, .05, .2, 'P'), 95.1229424501)
        self.assertEqual(common.bs_price(100, 0, 1, .05, .2, 'C'), 100)

    def test_bs_rejects_invalid_inputs(self):
        for values in [(-1,100,1,.05,.2),(100,100,1,.05,-.2),(100,100,1,.05,float('nan'))]:
            with self.assertRaises(ValueError): common.bs_price(*values)
            with self.assertRaises(ValueError): common.bs_greeks(*values)

    def test_bs_kink_does_not_claim_zero_sensitivities(self):
        spot = 100 * math.exp(-.05)
        self.assertEqual(common.bs_price(spot, 100, 1, .05, 0), 0)
        with self.assertRaisesRegex(ValueError, 'undefined'):
            common.bs_greeks(spot, 100, 1, .05, 0)
        with self.assertRaisesRegex(ValueError, 'undefined'):
            common.bs_greeks(100, 100, 0, .05, .2)

    def test_dividend_locales(self):
        with patch.object(common, 'run_cli', return_value={'list': [
            {'desc':'Dividend: USD 0.26/share'}, {'desc':'每股派息 5.30 HKD'}]}):
            result = common.get_dividend_history('X.US')
        self.assertEqual([(x.get('amount'), x.get('currency')) for x in result],
                         [(.26, 'USD'), (5.3, 'HKD')])

    def test_market_date_uses_new_york_not_shanghai_midnight(self):
        instant = datetime(2026, 11, 3, 1, tzinfo=timezone.utc)
        self.assertEqual(str(common.market_date('X.US', now=instant)), '2026-11-02')
        self.assertEqual(str(common.market_date('700.HK', now=instant)), '2026-11-03')

    def test_dst_transition_fallback_uses_utc_transition_hour(self):
        for instant, expected in [(datetime(2026,3,8,6,59,tzinfo=timezone.utc),-5),
                                  (datetime(2026,3,8,7,tzinfo=timezone.utc),-4),
                                  (datetime(2026,11,1,5,59,tzinfo=timezone.utc),-4),
                                  (datetime(2026,11,1,6,tzinfo=timezone.utc),-5)]:
            self.assertEqual(common.market_now('US', now=instant).utcoffset().total_seconds()/3600,expected)

    def test_expiry_day_has_time_value_until_market_close(self):
        with patch.object(common, 'market_now', return_value=datetime(2026,11,6,20,tzinfo=timezone.utc)):
            self.assertAlmostEqual(common.days_to_years('2026-11-06'), 1/(365*24))
        self.assertEqual(common.days_to_years('2026-11-06', today='2026-11-05'), 1/365)

    def test_default_expirations_exclude_same_day_after_close(self):
        expiries = [{'expiry_date': '2026-11-06'}, {'expiry_date': '2026-11-13'}]
        for hour, expected in [(15, ['2026-11-06', '2026-11-13']), (17, ['2026-11-13'])]:
            current = datetime(2026, 11, 6, hour, tzinfo=timezone(timedelta(hours=-5)))
            with self.subTest(hour=hour), patch.object(common, 'market_now', return_value=current), patch.object(common, 'run_cli', return_value=expiries):
                self.assertEqual(common.get_option_expirations('X.US'), expected)

    def test_unknown_capital_units_are_not_silently_scaled(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(common,'run_cli',return_value={
            'capital_in':{'large':'100'},'capital_out':{'large':'30'}}):
            result=common.get_capital_flow_snapshot('X.US')
        self.assertEqual(result['net']['large'],70)
        self.assertFalse(result['unit_verified'])
        self.assertIsNone(result['net']['medium'])

    def test_capital_preserves_small_source_values(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(common, 'run_cli', return_value={
            'capital_in': {'large': .004, 'medium': .003, 'small': .002},
            'capital_out': {'large': 0, 'medium': 0, 'small': 0}}):
            result = common.get_capital_flow_snapshot('X.US')
        self.assertEqual(result['net']['large'], .004)
        self.assertAlmostEqual(result['net']['total'], .009)
        raw = [{'time': '10:00', 'inflow': .0001}, {'time': '10:01', 'inflow': .0007}]
        with patch.dict(os.environ, {'LBR_CAPITAL_FLOW_MODE': 'cumulative'}, clear=True), patch.object(common, 'run_cli', return_value=raw):
            rows = common.get_capital_flow_series('X.US')
        self.assertAlmostEqual(rows[1]['minute_delta'], .0006)

    def test_capital_flow_semantics_require_explicit_setting(self):
        raw=[{'time':'10:00','inflow':'100'},{'time':'10:01','inflow':'120'}]
        with patch.dict(os.environ, {}, clear=True), patch.object(common,'run_cli',return_value=raw):
            rows=common.get_capital_flow_series('X.US')
        self.assertIsNone(rows[1]['minute_delta'])
        with patch.dict(os.environ, {'LBR_CAPITAL_FLOW_MODE':'cumulative','LBR_CAPITAL_SCALE':'10000'},clear=True), patch.object(common,'run_cli',return_value=raw):
            rows=common.get_capital_flow_series('X.US')
        self.assertEqual(rows[1]['minute_delta'],200000)

    def test_nonstandard_option_chain_is_not_used_as_standard(self):
        with patch.object(common,'run_cli',return_value=[{'strike':'100','standard':False}, {'strike':'110','standard':True}]):
            rows=common.get_option_chain('X.US','2027-01-15')
        self.assertEqual([r['strike'] for r in rows], [110])

    def test_cumulative_gap_is_not_a_minute_flow(self):
        raw = [{'time': '10:00', 'inflow': 100},
               {'time': '10:05', 'inflow': 125},
               {'time': '10:06', 'inflow': 130}]
        with patch.dict(os.environ, {'LBR_CAPITAL_FLOW_MODE': 'cumulative'}, clear=True), patch.object(common, 'run_cli', return_value=raw):
            rows = common.get_capital_flow_series('X.US')
        self.assertIsNone(rows[1]['minute_delta'])
        self.assertEqual(rows[1]['interval_delta'], 25)
        self.assertEqual(rows[1]['interval_seconds'], 300)
        self.assertEqual(rows[2]['minute_delta'], 5)

    def test_unknown_or_duplicate_time_cannot_produce_minute_delta(self):
        for raw in [[{'inflow': 100}, {'inflow': 120}],
                    [{'time': '10:00', 'inflow': 100}, {'time': '10:00', 'inflow': 120}]]:
            with self.subTest(raw=raw), patch.dict(os.environ, {'LBR_CAPITAL_FLOW_MODE': 'cumulative'}, clear=True), patch.object(common, 'run_cli', return_value=raw):
                rows = common.get_capital_flow_series('X.US')
                self.assertIsNone(rows[1]['minute_delta'])


if __name__ == '__main__': unittest.main()
