"""v0.6.6 PR-1 回归测试:
  - v0.32.0 批量部分未知代码容错 (`run_cli(..., allow_partial=True)` + `get_batch_quotes`)
  - 宏观日历修复与分级 (`info['star']` / `bucket['date']` / `tier1` / `--star` / `--tier1`)
  - 大盘环境评估 (`get_market_regime.py`: Risk-Off / Caution / Risk-On / HK)
  - `analyze_buy_sell.py` 与 `daily_briefing.py` 大盘环境及 3 星宏观联动
  - `check_entry_rules.py` 半自动规则打通 (`B8` 行业精确映射 / `D11` 延长时段+新闻自动分诊 / `D6` 收涨及同行对比自动排雷 / `--strict-regime`)
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "calendar", "decision", "market", "sentiment", "technical"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))
sys.path.insert(0, _HERE)

import common  # noqa: E402
import analyze_buy_sell as dashboard  # noqa: E402
import check_entry_rules as cer  # noqa: E402
import daily_briefing as briefing  # noqa: E402
import get_macro_calendar as macro_cal  # noqa: E402
import get_market_regime as regime_mod  # noqa: E402
from tests import test_entry_rules_v050 as fixtures  # noqa: E402


class TestCli0320BatchAndHelpers(unittest.TestCase):
    """v0.32.0 批量部分失败容错与 common 新增辅助函数。"""

    def test_run_cli_allow_partial_recovers_valid_json_list_on_nonzero_exit(self):
        payload = json.dumps([{"symbol": "AAPL.US", "last": "354.07"}])
        proc = subprocess.CompletedProcess(
            args=["longbridge", "quote", "AAPL.US", "BAD.US"],
            returncode=1,
            stdout=payload,
            stderr='{"error":{"message":"no security matches BAD.US"}}',
        )
        with mock.patch.object(common, "find_longbridge_cli", return_value="longbridge"), \
             mock.patch.object(common, "_throttle"), \
             mock.patch("subprocess.run", return_value=proc):
            out = common.run_cli("quote", "AAPL.US", "BAD.US", retries=0, allow_partial=True)
            self.assertEqual(out, [{"symbol": "AAPL.US", "last": "354.07"}])
            with self.assertRaises(common.LongbridgeCliError):
                common.run_cli("quote", "AAPL.US", "BAD.US", retries=0, allow_partial=False)

    def test_run_cli_allow_partial_does_not_swallow_auth_errors_or_empty_stdout(self):
        proc_empty = subprocess.CompletedProcess(
            args=["longbridge", "quote", "BAD.US"], returncode=1, stdout="", stderr="invalid symbol"
        )
        proc_auth = subprocess.CompletedProcess(
            args=["longbridge", "quote", "AAPL.US"],
            returncode=1,
            stdout='[{"symbol": "AAPL.US"}]',
            stderr="token expired",
        )
        with mock.patch.object(common, "find_longbridge_cli", return_value="longbridge"), \
             mock.patch.object(common, "_throttle"), \
             mock.patch("subprocess.run", side_effect=[proc_empty, proc_auth]):
            with self.assertRaises(common.LongbridgeCliError):
                common.run_cli("quote", "BAD.US", retries=0, allow_partial=True)
            with self.assertRaises(common.LongbridgeCliError):
                common.run_cli("quote", "AAPL.US", retries=0, allow_partial=True)

    def test_get_batch_quotes_dedups_and_parses(self):
        raw = [
            {
                "symbol": ".VIX.US", "last": "30.720", "prev_close": "26.360",
                "change_percentage": "16.54", "volume": 0,
                "pre_market": None, "post_market": None, "overnight": None,
            },
            {
                "symbol": "SPY.US", "last": "718.780", "prev_close": "722.290",
                "change_percentage": "-0.49", "volume": 64343213,
                "pre_market": {"last": "705.320", "timestamp": "2026-11-25T13:10:00Z"},
            },
        ]
        with mock.patch.object(common, "run_cli", return_value=raw) as spy:
            got = common.get_batch_quotes([".VIX.US", "SPY.US", "spy.us", ""])
            spy.assert_called_once_with("quote", ".VIX.US", "SPY.US", allow_partial=True)
        self.assertIn(".VIX.US", got)
        self.assertEqual(got[".VIX.US"]["regular_price"], 30.72)
        self.assertEqual(got["SPY.US"]["extended"][0]["price"], 705.32)

    def test_get_finance_calendar_star_and_industry_rank_count(self):
        with mock.patch.object(common, "run_cli", return_value={"list": []}) as spy:
            common.get_finance_calendar("macrodata", market="US", count=30, star=3)
            spy.assert_called_once_with(
                "finance-calendar", "macrodata", "--market", "US", "--star", "3", "--count", "30"
            )
        with mock.patch.object(common, "run_cli", return_value={"items": []}) as spy2:
            common.get_industry_rank("US")
            spy2.assert_called_once_with("industry-rank", "--market", "US", "--count", "200")


class TestMacroCalendarFixesAndTiering(unittest.TestCase):
    """macrodata 顶层 star、bucket date 拼接与 Tier-1 核心催化分级。"""

    def test_flatten_macro_reads_top_star_date_and_tier1(self):
        buckets = [{
            "date": "2026-11-25",
            "count": 2,
            "infos": [
                {
                    "content": "美国, 核心PCE物价指数 同比",
                    "date": "21:30",
                    "datetime": "1795613400",
                    "star": 3,
                    "market": "US",
                    "data_kv": [
                        {"type": "previous", "value": "2.8%", "value_raw": "2.8"},
                        {"type": "estimate", "value": "2.8%", "value_raw": "2.8"},
                        {"type": "actual", "value": "--", "value_raw": ""},
                    ],
                },
                {
                    "content": "美国, 里士满联储综合指数",
                    "date": "23:00",
                    "datetime": "1795618800",
                    "star": 3,
                    "market": "US",
                    "data_kv": [],
                },
                {
                    "content": "美国, 已受检出口玉米",
                    "date": "00:00",
                    "datetime": "1795536000",
                    "star": 1,
                    "market": "US",
                    "data_kv": [],
                },
            ],
        }]
        with mock.patch.object(macro_cal, "get_finance_calendar", return_value=buckets), \
             contextlib.redirect_stdout(io.StringIO()):
            full = macro_cal.fetch_macro_calendar(market="US", output_json=False)
            t1 = macro_cal.fetch_macro_calendar(market="US", tier1_only=True, output_json=False)
        self.assertEqual(full["tier1_count"], 1)
        self.assertEqual(full["events"][0]["date"], "2026-11-25 21:30")
        self.assertEqual(full["events"][0]["star"], 3)
        self.assertEqual(full["events"][0]["tier"], "tier1")
        self.assertFalse(full["events"][0]["released"])
        self.assertEqual(full["events"][1]["tier"], "tier2")
        self.assertEqual(full["events"][2]["tier"], "regular")
        self.assertEqual([e["name"] for e in t1["events"]], ["美国, 核心PCE物价指数 同比"])

    def test_classify_macro_tier_supports_cli_english_names(self):
        for title in (
            "United States, Personal Consumption Expenditure, Personal consumption expenditures less food and energy, Chg Y/Y",
            "United States, Employment, Nonfarm payroll, total, Absolute change",
            "United States, Unemployment, Rate",
            "United States, Jobless Claims, National, Initial",
            "United States, Economic Forecasts, Federal Reserve, Median, Federal funds rate projection",
        ):
            self.assertEqual(macro_cal.classify_macro_tier(title, 3), "tier1", title)
        self.assertEqual(
            macro_cal.classify_macro_tier("United States, Manufacturers New Orders, Durable goods total, Chg P/P", 3),
            "tier2",
        )


class TestMarketRegimeEngine(unittest.TestCase):
    """大盘环境状态识别: Risk-Off / Caution / Risk-On / HK。"""

    def _klines(self, base: float, step: float, n: int = 210):
        return [{"close": str(round(base + i * step, 2))} for i in range(n)]

    def test_us_risk_off_on_vix_panic_and_premarket_gap(self):
        now = datetime(2026, 11, 25, 13, 30, tzinfo=timezone.utc)
        quotes = {
            ".VIX.US": {"symbol": ".VIX.US", "regular_price": 30.72, "change_percentage": 16.54, "extended": []},
            "SPY.US": {
                "symbol": "SPY.US", "regular_price": 718.78, "change_percentage": -0.49,
                "extended": [{"source": "pre_market", "source_label": "盘前", "price": 705.32, "time": now}],
            },
            "QQQ.US": {
                "symbol": "QQQ.US", "regular_price": 638.10, "change_percentage": -1.99,
                "extended": [{"source": "pre_market", "source_label": "盘前", "price": 620.09, "time": now}],
            },
        }
        macro_buckets = [{
            "date": "2026-11-25",
            "infos": [{
                "content": "美国, 核心PCE物价指数 同比", "date": "08:30",
                "datetime": str(int(now.timestamp()) + 3600), "star": 3,
                "data_kv": [{"type": "estimate", "value": "2.8%", "value_raw": "2.8"}],
            }],
        }]
        with mock.patch.object(regime_mod, "get_batch_quotes", return_value=quotes), \
             mock.patch.object(regime_mod, "get_kline_adjusted", return_value=self._klines(700, 0.1)), \
             mock.patch.object(regime_mod, "get_finance_calendar", return_value=macro_buckets):
            reg = regime_mod.assess_market_regime("US", now=now)
        self.assertEqual(reg["regime"], "risk_off")
        self.assertEqual(reg["max_bull_penalty"], 12)
        self.assertEqual(reg["vix"]["state"], "panic")
        self.assertEqual(len(reg["tier1_24h"]), 1)
        self.assertLess(reg["benchmarks"]["SPY.US"]["ext_gap_pct"], -1.5)

    def test_us_caution_when_tier1_within_24h_even_with_calm_vix(self):
        now = datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc)
        quotes = {
            ".VIX.US": {"symbol": ".VIX.US", "regular_price": 15.2, "change_percentage": -1.0, "extended": []},
            "SPY.US": {"symbol": "SPY.US", "regular_price": 730.0, "change_percentage": 0.2, "extended": []},
            "QQQ.US": {"symbol": "QQQ.US", "regular_price": 650.0, "change_percentage": 0.3, "extended": []},
        }
        macro_buckets = [{
            "date": "2026-12-10",
            "infos": [{
                "content": "美国, CPI 同比", "date": "21:30",
                "datetime": str(int(now.timestamp()) + 1800), "star": 3,
                "data_kv": [{"type": "actual", "value": "--", "value_raw": ""}],
            }],
        }]
        with mock.patch.object(regime_mod, "get_batch_quotes", return_value=quotes), \
             mock.patch.object(regime_mod, "get_kline_adjusted", side_effect=[self._klines(520, 1.0), self._klines(440, 1.0)]), \
             mock.patch.object(regime_mod, "get_finance_calendar", return_value=macro_buckets):
            reg = regime_mod.assess_market_regime("US", now=now)
        self.assertEqual(reg["regime"], "caution")
        self.assertEqual(reg["max_bull_penalty"], 6)
        self.assertEqual(len(reg["tier1_24h"]), 1)

    def test_us_risk_on_above_mas_and_low_vix(self):
        now = datetime(2026, 11, 24, 16, 0, tzinfo=timezone.utc)
        quotes = {
            ".VIX.US": {"symbol": ".VIX.US", "regular_price": 14.5, "change_percentage": -2.1, "extended": []},
            "SPY.US": {"symbol": "SPY.US", "regular_price": 730.0, "change_percentage": 0.6, "extended": []},
            "QQQ.US": {"symbol": "QQQ.US", "regular_price": 650.0, "change_percentage": 0.9, "extended": []},
        }
        with mock.patch.object(regime_mod, "get_batch_quotes", return_value=quotes), \
             mock.patch.object(regime_mod, "get_kline_adjusted", side_effect=[self._klines(520, 1.0), self._klines(440, 1.0)]), \
             mock.patch.object(regime_mod, "get_finance_calendar", return_value=[]):
            reg = regime_mod.assess_market_regime("US", now=now)
        self.assertEqual(reg["regime"], "risk_on")
        self.assertEqual(reg["max_bull_penalty"], 0)
        self.assertTrue(reg["benchmarks"]["SPY.US"]["above_ma20"])
        self.assertTrue(reg["benchmarks"]["QQQ.US"]["above_ma50"])

    def test_hk_regime_uses_2800_and_market_temp(self):
        now = datetime(2026, 11, 25, 4, 0, tzinfo=timezone.utc)
        quotes = {"2800.HK": {"symbol": "2800.HK", "regular_price": 25.0, "change_percentage": 0.8, "extended": []}}
        with mock.patch.object(regime_mod, "get_batch_quotes", return_value=quotes), \
             mock.patch.object(regime_mod, "get_kline_adjusted", return_value=self._klines(18.0, 0.03)), \
             mock.patch.object(regime_mod, "get_market_temp", return_value={"temperature": 62.0}), \
             mock.patch.object(regime_mod, "get_finance_calendar", return_value=[]):
            reg = regime_mod.assess_market_regime("HK", now=now)
        self.assertEqual(reg["regime"], "risk_on")
        self.assertEqual(reg["market_temp"]["temperature"], 62.0)


class TestDashboardAndBriefingIntegration(unittest.TestCase):
    """买卖仪表盘与每日简报集成 Market Regime。"""

    def test_dashboard_combines_earnings_and_regime_penalty_capped_and_directional(self):
        base = dashboard.common.market_now("US")
        today_str = base.strftime("%Y.%m.%d")
        reg = {
            "regime": "risk_off", "label": "🔴 Risk-Off(系统性避险)",
            "max_bull_penalty": 12, "summary": "VIX 30.72(+16.5%)",
        }
        bulls, bears, reg_box = [], [], {}
        with mock.patch.object(dashboard, "get_finance_calendar", return_value=[{"infos": [{"date": today_str}]}]), \
             mock.patch.object(dashboard, "assess_market_regime", return_value=reg):
            pen, note = dashboard._dim_event("AAPL.US", bulls, bears, include_regime=True, regime_out=reg_box)
        self.assertEqual(pen, 15)  # min(15, 7 + 12)
        self.assertIn("Risk-Off", note)
        self.assertTrue(any("大盘/宏观" in b for b in bears))
        self.assertEqual(reg_box["regime"], "risk_off")

    def test_daily_briefing_renders_market_regime_section(self):
        reg = {
            "regime": "risk_off", "label": "🔴 Risk-Off(系统性避险)",
            "summary": "VIX 30.72(+16.5%), SPY 705.32(盘前 -1.9%)",
            "vix": {"level": 30.72, "change_pct": 16.54, "state": "panic"},
            "benchmarks": {"SPY.US": {"symbol": "SPY.US", "price": 705.32, "source_label": "盘前",
                                      "change_pct": -1.87, "ma20": 715.0, "ma50": 710.0}},
            "tier1_24h": [{"name": "美国, 核心PCE物价指数 同比", "date": "2026-11-25 21:30",
                           "estimate": "2.8%", "previous": "2.8%", "tier": "tier1"}],
            "star3_upcoming": [],
        }
        buf = io.StringIO()
        with mock.patch.object(briefing, "get_market_temp", return_value={"temperature": 39, "valuation": 26, "sentiment": 53}), \
             mock.patch.object(briefing, "assess_market_regime", return_value=reg), \
             mock.patch.object(briefing, "get_heat_rank", return_value={"lists": []}), \
             mock.patch.object(briefing, "get_top_movers", return_value={"events": []}), \
             mock.patch.object(briefing, "get_anomaly", return_value={"changes": []}), \
             contextlib.redirect_stdout(buf):
            out = briefing.generate_briefing(market="US", include_pc=False, include_regime=True, output_json=False)
        self.assertIn("market_regime", out["sections"])
        text = buf.getvalue()
        self.assertIn("大盘环境与重磅宏观", text)
        self.assertIn("核心PCE", text)


class TestEntryRulesPhase3Automation(unittest.TestCase):
    """Phase 3: D11 / D6 / B8 自动判定与 --strict-regime。"""

    def test_d11_auto_triage_three_zones(self):
        # 1. 常规时段 → clear
        self.assertEqual(cer._auto_d11("AAPL.US", {"source": "regular"}, 0.02, 20)[0], "clear")
        # 2. 盘前小幅波动 → clear
        quiet = cer._auto_d11(
            "AAPL.US",
            {"source": "pre_market", "source_label": "盘前", "price": 351.2, "regular_price": 354.0},
            0.02, 20,
        )
        self.assertEqual(quiet[0], "clear")
        # 3. 盘前非财报大幅异动 + 新闻标题 → triggered
        with mock.patch.object(cer, "get_symbol_news", return_value=[{"title": "FDA rejects key filing"}]):
            shock = cer._auto_d11(
                "XYZ.US",
                {"source": "pre_market", "source_label": "盘前", "price": 90.0, "regular_price": 100.0},
                0.02, 30,
            )
            self.assertEqual(shock[0], "triggered")
            self.assertIn("FDA rejects", shock[1])
            # 4. 财报窗口即使大跳空也留待人工确认
            earn = cer._auto_d11(
                "XYZ.US",
                {"source": "post_market", "source_label": "盘后", "price": 90.0, "regular_price": 100.0},
                0.02, 0,
            )
            self.assertEqual(earn[0], "manual")
            self.assertIn("临近财报", earn[1])

    def test_d6_auto_clear_on_up_day_sector_outperform_or_peers(self):
        # 1. 上个完整交易日收涨/平 → clear
        f_up = {"c": [100.0, 100.8]}
        self.assertEqual(cer._auto_d6("AAPL.US", f_up, intraday_bar=False, industry_info=None)[0], "clear")
        # 2. 下跌但跑赢所属行业 → clear
        f_dn = {"c": [100.0, 99.0]}  # -1.0%
        self.assertEqual(
            cer._auto_d6("AAPL.US", f_dn, intraday_bar=False,
                         industry_info={"industry_name": "半导体", "chg": -0.025})[0],
            "clear",
        )
        # 3. 同行样本里有 >=30% 跌得更深 → clear
        val = {"peers": {"pe": {"list": [
            {"symbol": "P1.US"}, {"symbol": "P2.US"}, {"symbol": "P3.US"}, {"symbol": "P4.US"},
        ]}}}
        p_quotes = {
            "P1.US": {"change_percentage": -3.0},
            "P2.US": {"change_percentage": -2.5},
            "P3.US": {"change_percentage": 0.5},
            "P4.US": {"change_percentage": -0.2},
        }
        with mock.patch.object(cer, "get_valuation", return_value=val), \
             mock.patch.object(cer, "get_batch_quotes", return_value=p_quotes):
            res = cer._auto_d6("AAPL.US", f_dn, intraday_bar=False, industry_info=None)
        self.assertEqual(res[0], "clear")
        self.assertIn("2/4", res[1])

    def test_strict_regime_blocks_matched_setup_in_analyze(self):
        bars = fixtures.TestBuySetups()._b1_bars()
        args = SimpleNamespace(
            lookback=60, max_stop_pct=8, min_stop_pct=0.0, target_price=110.0,
            sector_top_decline="no", recent_stopout="no", familiar="yes",
            prepost_move="no", sector_breakout="no", earnings_days=20,
            no_heat=True, no_regime=False, strict_regime=True,
            now="2026-11-25 10:00", sector=None, sector_chg_pct=3.0,
            smallcap_usd=2e9, output_json=True,
        )
        reg = {"regime": "risk_off", "label": "🔴 Risk-Off(系统性避险)",
               "summary": "VIX 30.72(+16.5%)", "tier1_24h": []}
        with mock.patch.object(cer, "get_kline_adjusted", return_value=bars), \
             mock.patch.object(cer, "get_underlying_price", return_value=105.0), \
             mock.patch.object(cer, "get_underlying_price_info", return_value={"price": 105.0, "source": "regular"}), \
             mock.patch.object(cer, "regular_session_price", return_value=105.0), \
             mock.patch.object(cer, "_closed_dates", return_value=set()), \
             mock.patch.object(cer, "assess_market_regime", return_value=reg), \
             contextlib.redirect_stdout(io.StringIO()):
            res = cer.analyze("TEST.US", args)
        self.assertEqual(res["verdict"], "❌ 不买")
        self.assertTrue(any("大盘过滤" in r for r in res["verdict_reasons"]))
        self.assertEqual(res["market_regime"]["regime"], "risk_off")


if __name__ == "__main__":
    unittest.main()
