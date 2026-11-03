from contextlib import redirect_stdout
from datetime import date
from io import StringIO
import unittest
from unittest.mock import patch

from scripts.flow import get_short_sale as short
from scripts.fundamental import get_consensus as consensus
from scripts.fundamental import get_dividend_quality as dividend
from scripts.fundamental import get_financial_health as health
from scripts.fundamental import get_insider_trades as insider
from scripts.intraday import get_trade_flow as trades
from scripts.intraday import get_vwap_analysis as vwap
from scripts.market import calc_anomaly_score as anomaly
from scripts.market import get_ah_premium as premium


class AuditMarketDataTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.output = StringIO()
        capture = redirect_stdout(self.output)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def test_anomaly_full_score(self):
        patch.object(anomaly, "get_anomaly", return_value={"changes": [{}] * 5}).start()
        patch.object(anomaly, "get_capital_flow_snapshot", return_value={
            "net": {"large": 3e6}, "capital_in": {"large": 3e6},
            "capital_out": {"large": 0},
        }).start()
        patch.object(anomaly, "_get_quote", return_value={"change_pct": 8}).start()
        patch.object(anomaly, "get_top_movers", return_value={
            "events": [{"stock": {"symbol": "TEST.US"}}],
        }).start()
        result = anomaly.calc_score("TEST.US", output_json=True)
        self.assertEqual(result["anomaly_score"], 100)
        self.assertIn("强异动", result["intensity"])

    def test_dividend_window_uses_as_of_date(self):
        rows = [{"ex_date": day, "amount": amount, "currency": "USD"}
                for day, amount in [("2025.12.15", 2), ("2026.02.15", 1), ("2026.12.15", 1)]]
        patch.object(dividend, "get_dividend_history", return_value=rows).start()
        patch.object(dividend, "get_underlying_price", return_value=10).start()
        patch.object(dividend, "market_date", return_value=date(2026, 11, 3)).start()
        self.assertEqual(dividend.analyze("TEST.US", quiet=True)["ttm_yield_pct"], 30)

    def test_losses_do_not_receive_cash_conversion_green(self):
        accounts = [{"name": name, "values": [{"value": value, "period": period}]}
                    for name, value, period in [("净利润", -10, "Q2"), ("自由现金流", -20, "Q2")]]
        report = {"list": {"IS": {"indicators": [{"accounts": accounts}]}}}
        patch.object(health, "get_financial_report", return_value=report).start()
        result = health.analyze("TEST.US", quiet=True)
        self.assertIsNone(result["computed"]["earnings_quality_pct"])
        self.assertEqual(result["greens"], 0)

    def test_ah_premium_single_point_has_no_trend(self):
        result = premium._analyze([{"ahpremium_rate": -0.3}])
        self.assertIsNone(result["trend"]["direction"])

    def test_insider_exercise_is_not_a_purchase(self):
        self.assertEqual(insider._classify("EXERCISE", "M"), "行权/转换")
        self.assertEqual(insider._classify("", "P"), "买入")

    def test_trade_estimate_handles_missing_price(self):
        patch.object(trades, "get_trades", return_value=[
            {"direction": "Up", "volume": 100, "price": None},
        ]).start()
        result = trades.analyze("TEST.US")
        self.assertIsNone(result["buy_amount_ratio_pct"])
        self.assertNotIn("主动买", result["verdict"])

    def test_latest_missing_short_rate_does_not_become_zero(self):
        rows = [{"rate": rate, "timestamp": 1700000000 + index * 86400}
                for index, rate in enumerate([0.2, 0.2, 0.2, None, None, None])]
        patch.object(short, "get_short_trades", return_value={"data": rows}).start()
        result = short.fetch_short_sale("TEST.US", output_json=True)
        self.assertIsNone(result["latest_rate"])
        self.assertIn("不足", result["trend"])

    def test_vwap_percentage_uses_valid_pairs(self):
        rows = [{"price": 101, "avg_price": 100}] * 2 + [{"price": None, "avg_price": 100}] * 9
        patch.object(vwap, "get_intraday", return_value=rows[::-1]).start()
        result = vwap.analyze("TEST.US", output_json=True)
        self.assertEqual(result["above_vwap_ratio_pct"], 100)
        self.assertIn("不足", result["verdict"])

    def test_zero_consensus_has_no_percentage_deviation(self):
        self.assertEqual(consensus._beat_miss(0, 0.1), ("超预期", None))

    def test_capital_unknown_semantics_hide_peaks_and_cumulative(self):
        from scripts.flow import get_capital_flow as capital
        rows = [{"time": "2026-01-02 13:30:00", "inflow": 23, "minute_delta": None,
                 "flow_mode": "unknown", "amount_unit": "source_unit", "unit_verified": False}]
        patch.object(capital, "get_capital_flow_series", return_value=rows).start()
        result = capital.fetch_capital_flow("TEST.US", flow=True, output_json=True)
        self.assertIsNone(result["final_cumulative"])
        self.assertIsNone(result["peak_inflow"])

    def test_trade_tail_uses_timestamps(self):
        rows = [{"timestamp": i + 100, "volume": 10, "price": 20,
                 "direction": "Up" if i < 30 else "Down"} for i in range(60)]
        patch.object(trades, "get_trades", return_value=rows).start()
        self.assertIn("偏卖", trades.analyze("TEST.US", output_json=True)["tail_mood"])

    def test_vwap_exact_time_not_row_offset(self):
        base = 1700000000
        rows = [{"price": 100, "avg_price": 99, "timestamp": base},
                {"price": 102, "avg_price": 101, "timestamp": base + 1800}]
        patch.object(vwap, "get_intraday", return_value=rows).start()
        self.assertEqual(vwap.analyze("TEST.US", output_json=True)["vwap_trend_30m"], "上行")

    def test_dividend_mixed_currencies_have_no_yield(self):
        rows = [{"ex_date": "2026.10.02", "amount": 1, "currency": c} for c in ("USD", "CNY")]
        patch.object(dividend, "get_dividend_history", return_value=rows).start()
        patch.object(dividend, "get_underlying_price", return_value=10).start()
        patch.object(dividend, "market_date", return_value=date(2026, 11, 3)).start()
        result = dividend.analyze("TEST.US", quiet=True)
        self.assertIsNone(result["ttm_yield_pct"])
        self.assertEqual(result["ttm_dividend_by_currency"], {"USD": 1, "CNY": 1})

    def test_health_does_not_use_margin_or_mismatched_period(self):
        accounts = [{"name": name, "values": [{"value": value, "period": period}]}
                    for name, value, period in [("归母净利润率", 40, "2026Q2"),
                                                ("净利润", 10, "2026Q2"),
                                                ("自由现金流", 20, "2026Q1")]]
        report = {"list": {"IS": {"indicators": [{"accounts": accounts}]}}}
        patch.object(health, "get_financial_report", return_value=report).start()
        result = health.analyze("TEST.US", quiet=True)
        self.assertEqual(result["items"]["net_profit"]["value"], 10)
        self.assertIsNone(result["computed"]["earnings_quality_pct"])
        self.assertIn("不足", result["verdict"])

    def test_capital_snapshot_missing_side_has_unknown_direction_and_raw_units(self):
        from scripts.flow import get_capital_flow as capital
        patch.object(capital, "get_capital_flow_snapshot", return_value={
            "capital_in": {"large": 20000}, "capital_out": {}, "net": {"large": None},
        }).start()
        result = capital.fetch_capital_flow("TEST.US")
        self.assertIn("不足", result["direction"])
        self.assertEqual(result["amount_unit"], "source_unit")
        printed = self.output.getvalue()
        self.assertIn("20,000.00（来源单位）", printed)
        self.assertNotIn("2.00万", printed)

    def test_anomaly_partial_data_has_no_full_intensity_rating(self):
        patch.object(anomaly, "get_anomaly", return_value={"changes": [{}] * 5}).start()
        patch.object(anomaly, "get_capital_flow_snapshot", return_value={
            "net": {"large": 1000000},
        }).start()
        patch.object(anomaly, "_get_quote", return_value={"change_pct": 8}).start()
        patch.object(anomaly, "get_top_movers", return_value={"events": []}).start()
        result = anomaly.calc_score("TEST.US", output_json=True)
        self.assertEqual(result["available_points"], 70)
        self.assertIsNone(result["dimensions"]["capital"]["score"])
        self.assertIn("资料不全", result["intensity"])

    def test_insider_unpriced_sale_does_not_imply_net_buying(self):
        patch.object(insider, "get_insider_trades", return_value=[
            {"code": "P", "value": 100},
            {"code": "S", "value": None},
        ]).start()
        result = insider.fetch_insider_trades("TEST.US", output_json=True)
        self.assertIsNone(result["stats"]["net_value"])
        self.assertIn("不足", result["stats"]["signal"])

    def test_large_trade_text_formats_numeric_and_offset_times_in_utc(self):
        rows = [
            {"timestamp": 1793701800, "price": 100, "volume": 2000, "direction": "Up"},
            {"time": "2026-11-03T09:00:00-05:00", "price": 100, "volume": 2000,
             "direction": "Down"},
        ]
        patch.object(trades, "get_trades", return_value=rows).start()
        trades.analyze("TEST.US")
        printed = self.output.getvalue()
        self.assertIn("10:30:00 UTC", printed)
        self.assertIn("14:00:00 UTC", printed)

    def test_capital_small_source_value_displays_nonzero(self):
        from scripts.flow import get_capital_flow as capital
        self.assertEqual(capital._fmt_money(0.00009, False), "9e-05（来源单位）")
