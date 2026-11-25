"""v0.6.7 PR-2 回归测试:
  - 进程内只读 CLI TTL 缓存、K 线超集复用、批量 quote 缓存预热、`LBR_CACHE_TTL=0` 关闭
  - 线程安全 `_throttle()` 并发节流
  - 只读 `watchlist` / `positions` / `assets` / `max-qty` 封装与标的过滤 (`is_equity_symbol`)
  - `check_entry_rules.py` 风险定仓计算器 (`calc_position_sizing` + `--capital` / `--use-account`)
  - `scan_watchlist.py` 批量自选/持仓扫描 (`--fast` / `--full` / `--only-setups` / 容错)
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import io
import json
import os
import subprocess
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "calendar", "decision", "fundamental", "market", "quote", "sentiment", "technical"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))
sys.path.insert(0, _HERE)

import common  # noqa: E402
import check_entry_rules as cer  # noqa: E402
import scan_watchlist as scanner  # noqa: E402
from tests import test_entry_rules_v050 as fixtures  # noqa: E402


class TestCliCacheAndThreadSafety(unittest.TestCase):
    def setUp(self):
        common.clear_cli_cache()

    def tearDown(self):
        common.clear_cli_cache()

    def test_run_cli_caches_readonly_commands_and_returns_deepcopy(self):
        proc = subprocess.CompletedProcess(
            args=["longbridge", "quote", "AAPL.US"],
            returncode=0,
            stdout=json.dumps([{"symbol": "AAPL.US", "last": "354.07"}]),
            stderr="",
        )
        with mock.patch.object(common, "find_longbridge_cli", return_value="longbridge"), \
             mock.patch.object(common, "_throttle"), \
             mock.patch("subprocess.run", return_value=proc) as spy:
            first = common.run_cli("quote", "AAPL.US")
            first[0]["last"] = "MUTATED"
            second = common.run_cli("quote", "AAPL.US")
            self.assertEqual(spy.call_count, 1)
            self.assertEqual(second[0]["last"], "354.07")

            # use_cache=False 绕过缓存再调一次
            common.run_cli("quote", "AAPL.US", use_cache=False)
            self.assertEqual(spy.call_count, 2)

    def test_run_cli_does_not_cache_mutating_watchlist_and_respects_ttl_zero(self):
        proc = subprocess.CompletedProcess(
            args=["longbridge"], returncode=0, stdout=json.dumps({"ok": True}), stderr=""
        )
        with mock.patch.object(common, "find_longbridge_cli", return_value="longbridge"), \
             mock.patch.object(common, "_throttle"), \
             mock.patch("subprocess.run", return_value=proc) as spy:
            common.run_cli("watchlist", "create", "MyGroup")
            common.run_cli("watchlist", "create", "MyGroup")
            self.assertEqual(spy.call_count, 2)

            with mock.patch.dict(os.environ, {"LBR_CACHE_TTL": "0"}):
                common.run_cli("quote", "NVDA.US")
                common.run_cli("quote", "NVDA.US")
                self.assertEqual(spy.call_count, 4)

    def test_kline_superset_tail_reuse_and_batch_quote_seeding(self):
        bars_100 = [{"time": str(i), "close": str(100 + i)} for i in range(100)]
        batch_quotes = [
            {"symbol": "AAPL.US", "last": "354.07", "prev_close": "349.08", "change_percentage": "1.43", "volume": 1},
            {"symbol": "MSFT.US", "last": "498.00", "prev_close": "495.00", "change_percentage": "0.61", "volume": 2},
        ]

        def fake_sub(cmd, **kwargs):
            if "kline" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(bars_100), "")
            if "quote" in cmd:
                return subprocess.CompletedProcess(cmd, 0, json.dumps(batch_quotes), "")
            raise AssertionError(cmd)

        with mock.patch.object(common, "find_longbridge_cli", return_value="longbridge"), \
             mock.patch.object(common, "_throttle"), \
             mock.patch("subprocess.run", side_effect=fake_sub) as spy:
            # 1) 100 根 K 线进缓存,随后请求 30 根直接切片返回
            k100 = common.get_kline_adjusted("AAPL.US", count=100)
            k30 = common.get_kline_adjusted("AAPL.US", count=30)
            self.assertEqual(len(k100), 100)
            self.assertEqual(len(k30), 30)
            self.assertEqual(k30[0]["close"], 170)

            # 2) 批量 quote 顺带回填单票缓存,后续单查 AAPL.US / MSFT.US 零额外调用
            common.get_batch_quotes(["AAPL.US", "MSFT.US"])
            q_aapl = common.get_underlying_quote("AAPL.US")
            q_msft = common.get_underlying_quote("MSFT.US")
            self.assertEqual(q_aapl["regular_price"], 354.07)
            self.assertEqual(q_msft["regular_price"], 498.0)
            self.assertEqual(spy.call_count, 2)

    def test_thread_safe_throttle_paces_concurrent_slots(self):
        orig_min, orig_ts = common._MIN_INTERVAL, common._last_call_ts
        try:
            common._MIN_INTERVAL = 0.03
            common._last_call_ts = time.monotonic() - 1.0
            t0 = time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda _: common._throttle(), range(4)))
            elapsed = time.monotonic() - t0
            self.assertGreaterEqual(elapsed, 0.075)  # 4 calls need >= 3 * 0.03s spacing
        finally:
            common._MIN_INTERVAL, common._last_call_ts = orig_min, orig_ts


class TestAccountAndWatchlistWrappers(unittest.TestCase):
    def test_is_equity_symbol_filters_options_warrants_indices_crypto(self):
        self.assertTrue(common.is_equity_symbol("AAPL.US"))
        self.assertTrue(common.is_equity_symbol("0700.HK"))
        self.assertTrue(common.is_equity_symbol("BRK.B.US", "STOCK"))
        self.assertFalse(common.is_equity_symbol(".VIX.US"))
        self.assertFalse(common.is_equity_symbol("BTCUSD.HAS"))
        self.assertFalse(common.is_equity_symbol("AAPL261218C350000.US"))
        self.assertFalse(common.is_equity_symbol("AAPL.US", "OPTION"))
        self.assertFalse(common.is_equity_symbol("61304.HK"))

    def test_watchlist_positions_assets_max_qty_parsers(self):
        wl = [
            {"id": 1, "name": "US Core", "securities": [
                {"symbol": "AAPL.US", "name": "Apple", "market": "US"},
                {"symbol": "0700.HK", "name": "Tencent", "market": "HK"},
                {"symbol": ".SPX.US", "name": "SPX", "market": "US"},
            ]},
            {"id": 2, "name": "Other", "securities": [{"symbol": "TSLA.US", "name": "Tesla", "market": "US"}]},
        ]
        pos = [
            {"symbol": "MSFT.US", "name": "Microsoft", "quantity": "12", "cost_price": "420.0", "market": "US", "asset_type": "STOCK"},
            {"symbol": "MSFT261218C500000.US", "quantity": "1", "market": "US", "asset_type": "OPTION"},
            {"symbol": "NVDA.US", "quantity": "0", "market": "US", "asset_type": "STOCK"},
        ]
        assets_list = [{"currency": "USD", "net_assets": "85000.50", "total_cash": "22000.0", "buy_power": "40000.0"}]
        mq_list = [{"field": "Symbol", "value": "AAPL.US"}, {"field": "Cash Max Qty", "value": "62"}, {"field": "Margin Max Qty", "value": "113"}]

        with mock.patch.object(common, "run_cli", side_effect=[wl, pos, assets_list, mq_list]):
            groups = common.get_watchlist_groups(group="core", market="US")
            stocks = common.get_stock_positions(market="US")
            acc = common.get_account_assets("USD")
            mq = common.estimate_max_purchase_qty("AAPL.US", 354.07)

        self.assertEqual(len(groups), 1)
        self.assertEqual([s["symbol"] for s in groups[0]["securities"]], ["AAPL.US"])
        self.assertEqual([p["symbol"] for p in stocks], ["MSFT.US"])
        self.assertEqual(acc["net_assets"], 85000.5)
        self.assertEqual(acc["buy_power"], 40000.0)
        self.assertEqual(mq["cash_max_qty"], 62)
        self.assertEqual(mq["margin_max_qty"], 113)


class TestPositionSizingCalculator(unittest.TestCase):
    def test_risk_budget_and_max_pos_cap_and_hk_lot_rounding(self):
        # Risk limited: capital 50,000 * 1% = $500; entry 100, stop 90 (risk $10/sh) -> 50 sh ($5,000 <= $10,000 cap)
        r1 = cer.calc_position_sizing(100.0, 90.0, 50000.0, risk_pct=1.0, max_pos_pct=20.0)
        self.assertEqual(r1["status"], "ok")
        self.assertEqual(r1["limiting_factor"], "risk_budget")
        self.assertEqual(r1["recommended_shares"], 50)
        self.assertEqual(r1["max_loss_amount"], 500.0)

        # Cap limited: tight stop 99 -> risk says 500 sh ($50,000), 20% cap limits to 100 sh ($10,000)
        r2 = cer.calc_position_sizing(100.0, 99.0, 50000.0, risk_pct=1.0, max_pos_pct=20.0)
        self.assertEqual(r2["limiting_factor"], "max_position_cap")
        self.assertEqual(r2["recommended_shares"], 100)

        # HK lot rounding + cash_max_qty & extended-hours stop breach warnings
        r3 = cer.calc_position_sizing(
            400.0, 385.0, 500000.0, risk_pct=1.0, max_pos_pct=20.0, lot_size=100,
            currency="HKD", cash_max_qty=100, margin_max_qty=200, ext_price=382.0,
        )
        # cap = 100,000 HKD -> 250 shares -> floor to 100-share lot = 200 shares
        self.assertEqual(r3["recommended_shares"], 200)
        self.assertEqual(len(r3["warnings"]), 2)

        # Invalid stop (>= entry)
        r4 = cer.calc_position_sizing(100.0, 102.0, 50000.0)
        self.assertEqual(r4["status"], "no_valid_stop")
        self.assertEqual(r4["recommended_shares"], 0)

    def test_check_entry_rules_analyze_attaches_position_sizing_for_use_account(self):
        bars = fixtures.TestBuySetups()._b1_bars()
        args = SimpleNamespace(
            lookback=60, max_stop_pct=8, min_stop_pct=0.0, target_price=110.0,
            sector_top_decline="no", recent_stopout="no", familiar="yes",
            prepost_move="no", sector_breakout="no", earnings_days=20,
            no_heat=True, no_regime=True, strict_regime=False,
            capital=None, use_account=True, risk_pct=1.0, max_pos_pct=20.0,
            now="2026-11-25 10:00", sector=None, sector_chg_pct=3.0,
            smallcap_usd=2e9, output_json=True,
        )
        with mock.patch.object(cer, "get_kline_adjusted", return_value=bars), \
             mock.patch.object(cer, "get_underlying_price", return_value=105.0), \
             mock.patch.object(cer, "get_underlying_price_info", return_value={"price": 105.0, "source": "regular"}), \
             mock.patch.object(cer, "regular_session_price", return_value=105.0), \
             mock.patch.object(cer, "_closed_dates", return_value=set()), \
             mock.patch.object(cer, "get_account_assets", return_value={"currency": "USD", "net_assets": 60000.0, "buy_power": 15000.0}), \
             mock.patch.object(cer, "estimate_max_purchase_qty", return_value={"cash_max_qty": 80, "margin_max_qty": 160}), \
             contextlib.redirect_stdout(io.StringIO()):
            res = cer.analyze("TEST.US", args)
        sz = res["position_sizing"]
        self.assertEqual(sz["status"], "ok")
        self.assertEqual(sz["capital_source"], "account_net_assets")
        self.assertEqual(sz["cash_max_qty"], 80)


class TestWatchlistScanner(unittest.TestCase):
    def test_scan_fast_and_full_modes_sort_actionable_first_and_survive_errors(self):
        b1_bars = fixtures.TestBuySetups()._b1_bars()
        down_bars = fixtures.gen([100.0] * 40 + fixtures.ramp(99.5, -0.01, 10))
        wl_groups = [{"id": 1, "name": "Main", "securities": [
            {"symbol": "AAA.US", "name": "DownCo", "market": "US"},
            {"symbol": "BBB.US", "name": "SetupCo", "market": "US"},
            {"symbol": "BAD.US", "name": "BadCo", "market": "US"},
        ]}]
        quotes = {
            "AAA.US": {"symbol": "AAA.US", "market": "US", "regular_price": down_bars[-1]["close"], "change_percentage": -1.0, "extended": []},
            "BBB.US": {"symbol": "BBB.US", "market": "US", "regular_price": 105.0, "change_percentage": 2.4, "extended": []},
            "BAD.US": {"symbol": "BAD.US", "market": "US", "regular_price": 50.0, "change_percentage": 0.0, "extended": []},
        }
        reg = {"regime": "risk_off", "label": "🔴 Risk-Off", "summary": "VIX 31"}

        def kline_side(sym, count=260):
            if sym == "AAA.US":
                return down_bars
            if sym == "BBB.US":
                return b1_bars
            raise RuntimeError("missing bars")

        buf = io.StringIO()
        with mock.patch.object(scanner, "get_watchlist_groups", return_value=wl_groups), \
             mock.patch.object(scanner, "get_batch_quotes", return_value=quotes), \
             mock.patch.object(scanner, "assess_market_regime", return_value=reg), \
             mock.patch.object(scanner, "_closed_dates", return_value=set()), \
             mock.patch.object(scanner, "get_kline_adjusted", side_effect=kline_side), \
             mock.patch.object(scanner, "get_finance_calendar", return_value=[]), \
             mock.patch.object(scanner, "tech_score", return_value={"technical_score": 78.0, "label": "🔥 强势"}), \
             contextlib.redirect_stdout(buf):
            fast_res = scanner.scan_watchlist(
                use_watchlist=True, mode="fast", capital=50000.0, workers=2, output_json=False
            )

        self.assertEqual(fast_res["scanned"], 3)
        self.assertEqual(fast_res["ok_count"], 2)
        self.assertEqual(fast_res["error_count"], 1)
        self.assertEqual(fast_res["setup_count"], 1)
        # Clean B1 setup (BBB.US) ranks #1 ahead of falling AAA.US and errored BAD.US
        self.assertEqual([x["symbol"] for x in fast_res["items"]], ["BBB.US", "AAA.US", "BAD.US"])
        self.assertIn("B1", fast_res["items"][0]["matched"])
        self.assertGreater(fast_res["items"][0]["recommended_shares"], 0)
        self.assertIn("Risk-Off", buf.getvalue())

        # Full mode + --positions unrealized P&L + --only-setups
        positions = [{"symbol": "BBB.US", "name": "SetupCo", "quantity": "10", "cost_price": "100.0", "market": "US"}]
        with mock.patch.object(scanner, "get_stock_positions", return_value=positions), \
             mock.patch.object(scanner, "get_batch_quotes", return_value={"BBB.US": quotes["BBB.US"]}), \
             mock.patch.object(scanner, "_closed_dates", return_value=set()), \
             mock.patch.object(scanner, "get_kline_adjusted", return_value=b1_bars), \
             mock.patch.object(scanner, "get_finance_calendar", return_value=[]), \
             mock.patch.object(scanner, "tech_score", return_value={"technical_score": 80.0, "label": "🔥 强势"}), \
             mock.patch.object(scanner, "dashboard_analyze", return_value={"composite_score": 74.0, "signal": "🟢🟢 看多"}), \
             contextlib.redirect_stdout(io.StringIO()):
            full_res = scanner.scan_watchlist(
                use_positions=True, mode="full", only_setups=True, include_regime=False, output_json=False
            )
        self.assertEqual(len(full_res["items"]), 1)
        self.assertEqual(full_res["items"][0]["composite_score"], 74.0)
        self.assertEqual(full_res["items"][0]["unrealized_pl_pct"], 5.0)


if __name__ == "__main__":
    unittest.main()
