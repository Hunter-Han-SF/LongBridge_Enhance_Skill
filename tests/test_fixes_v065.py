"""v0.6.5 修复回归: 2026-11-25 美股盘前实盘抽检发现的四组问题(AAPL.US / MSFT.US)。

覆盖:
  1. trade-stats 服务端截断防护: 仅返回顶部 50 档高价位(MSFT 占 5 日总成交 0.044%)时
     拒绝输出假 POC / Value Area, 主动买/卖量比改用 statistics 全样本口径
  2. 新挂牌周度期权链无 IV: get_option_volatility 与 analyze_buy_sell 按期限距离回退到
     最近的有有效 ATM IV 的到期日; HV 改用前复权 K 线; ATM 选档对齐常规时段价
  3. 跨时段与节假日边界:
     - us_market_holiday 与 _regular_session_state 排除感恩节/圣诞等美股全日休市及半日市
     - regular_session_price 复用已缓存的 regular_price 不重复调 quote
     - get_vwap_analysis 在常规时段未开盘时标注上一交易日常规时段并提示 --session all
     - calc_anomaly_score 接入延长时段报价与盘前/盘后涨跌幅
     - calc_expected_move / get_iv_term_structure 用常规时段价选链上 ATM
  4. 多点号代码 / 窄止损防护 / 仪表盘格式 / screener --count:
     - parse_underlying 兼容 BRK.B.US 与单字母 A.US
     - check_entry_rules 对延长时段跌破止损、--min-stop-pct 与 <0.5*ATR 窄止损告警
     - analyze_buy_sell 整数看多机构数、无重复表情、可读大单金额与权重标注
     - run_screener 支持 --count

运行: python -m unittest tests.test_fixes_v065 -v
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "decision", "fundamental", "intraday", "market", "quote", "screener", "technical"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))

import analyze_buy_sell as dashboard  # noqa: E402
import analyze_iv_crush as iv_crush  # noqa: E402
import calc_anomaly_score as anomaly  # noqa: E402
import calc_expected_move as expected_move  # noqa: E402
import check_entry_rules as entry  # noqa: E402
import common  # noqa: E402
import get_dividend_quality as dividend  # noqa: E402
import get_iv_term_structure as term_struct  # noqa: E402
import get_option_volatility as opt_vol  # noqa: E402
import get_trade_stats as trade_stats  # noqa: E402
import get_valuation_percentile as val_pctl  # noqa: E402
import get_vwap_analysis as vwap  # noqa: E402
import run_screener as screener  # noqa: E402


def _capture(func, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = func(*args, **kwargs)
    return res, buf.getvalue()


EST = timezone(timedelta(hours=-5))


class _PriceCacheCase(unittest.TestCase):
    def setUp(self):
        common._LAST_PRICE_INFO.clear()
        self.addCleanup(common._LAST_PRICE_INFO.clear)


# --------------------------------------------------------------------------- #
# 1. trade-stats 服务端截断防护
# --------------------------------------------------------------------------- #

# 取自 2026-11-25 实盘 MSFT.US: 5 日总成交 14,359,086 股, 但 trades 只有顶部 50 档合计 6,313 股
MSFT_TRUNCATED_STATS = {
    "statistics": {
        "avgprice": 495.38, "preclose": 492.5,
        "total_amount": 14359086, "buy": 1596445, "sell": 1775772, "neutral": 10986869,
    },
    "trades": [
        {"price": 501.665, "buy_amount": 0, "sell_amount": 0, "neutral_amount": 261},
        {"price": 501.67, "buy_amount": 0, "sell_amount": 20, "neutral_amount": 1224},
        {"price": 501.75, "buy_amount": 322, "sell_amount": 0, "neutral_amount": 381},
        {"price": 501.78, "buy_amount": 4000, "sell_amount": 0, "neutral_amount": 105},
    ],
}


class TestTradeStatsCoverageGuard(unittest.TestCase):
    def test_msft_truncated_sample_hides_poc_and_uses_statistics_imbalance(self):
        with patch.object(trade_stats, "get_trade_stats", return_value=MSFT_TRUNCATED_STATS):
            res, out = _capture(trade_stats.fetch_trade_stats, "MSFT.US", output_json=False)
        p = res["profile"]
        self.assertFalse(p["profile_complete"])
        self.assertIsNone(p["poc"])
        self.assertIsNone(p["vah"])
        self.assertIsNone(p["val"])
        self.assertEqual(p["sample_poc"], 501.78)
        self.assertLess(p["coverage_pct"], 0.1)
        # 截断样本里是买方 4322 vs 卖方 20 (sample=216.1), 全样本其实是 1,596,445 / 1,775,772 = 0.90 (均衡, 非买方占优)
        self.assertEqual(p["buy_sell_imbalance"], 0.9)
        self.assertEqual(p["imbalance_basis"], "statistics_5d")
        self.assertIn("价位明细被服务端截断", out)
        self.assertIn("均衡", out)
        self.assertNotIn("买方占优", out)
        self.assertNotIn("POC(最大成交价位)", out)

        # AAPL 实盘截断样本: 样本买/卖 5.33 vs 全样本 3,516,984 / 4,169,746 = 0.84(卖方占优)
        aapl_trunc = {
            "statistics": {"avgprice": 352.68, "preclose": 349.08,
                           "total_amount": 24169463, "buy": 3516984, "sell": 4169746, "neutral": 16482733},
            "trades": [{"price": 354.24, "buy_amount": 33636, "sell_amount": 413, "neutral_amount": 8421}],
        }
        with patch.object(trade_stats, "get_trade_stats", return_value=aapl_trunc):
            res_aapl, out_aapl = _capture(trade_stats.fetch_trade_stats, "AAPL.US", output_json=False)
        self.assertEqual(res_aapl["profile"]["buy_sell_imbalance"], 0.84)
        self.assertIn("卖方占优", out_aapl)

    def test_complete_coverage_outputs_poc_and_va(self):
        full = {
            "statistics": {"avgprice": 10.5, "preclose": 10.2,
                           "total_amount": 1000, "buy": 600, "sell": 300, "neutral": 100},
            "trades": [
                {"price": 10.0, "buy_amount": 200, "sell_amount": 100, "neutral_amount": 0},
                {"price": 10.5, "buy_amount": 300, "sell_amount": 150, "neutral_amount": 50},
                {"price": 11.0, "buy_amount": 100, "sell_amount": 50, "neutral_amount": 50},
            ],
        }
        with patch.object(trade_stats, "get_trade_stats", return_value=full):
            res, out = _capture(trade_stats.fetch_trade_stats, "700.HK", output_json=False)
        p = res["profile"]
        self.assertTrue(p["profile_complete"])
        self.assertEqual((p["poc"], p["val"], p["vah"]), (10.5, 10.0, 10.5))
        self.assertIn("POC(最大成交价位): 10.5", out)


# --------------------------------------------------------------------------- #
# 2. 空 IV 新链回退 + 前复权 K 线 + 常规时段 ATM 对齐
# --------------------------------------------------------------------------- #

class TestEmptyChainFallback(_PriceCacheCase):
    EXPIRIES = ["2026-12-18", "2026-12-31", "2027-01-08", "2027-01-15"]
    DAYS = {"2026-12-18": 23.0, "2026-12-31": 36.0, "2027-01-08": 44.0, "2027-01-15": 51.0}
    CHAINS = {
        "2026-12-18": [{"strike": 495.0, "call_iv": 0.25, "put_iv": 0.26, "standard": "true"}],
        "2026-12-31": [{"strike": 485.0, "call_iv": 0.31, "put_iv": 0.31, "standard": "true"},
                       {"strike": 495.0, "call_iv": 0.24, "put_iv": 0.24, "standard": "true"}],
        # 2027-01-08 刚挂牌周链: 44 天最接近 43.45 天, 但无 IV
        "2027-01-08": [{"strike": 495.0, "call_symbol": "MSFT270108C495000.US", "standard": "true"}],
        "2027-01-15": [{"strike": 495.0, "call_iv": 0.23, "put_iv": 0.24, "standard": "true"}],
    }

    @staticmethod
    def _closes(n):
        return [{"close": 490.0 if i % 2 == 0 else 495.0} for i in range(n)]

    def test_option_volatility_skips_empty_weekly_chain_and_uses_regular_atm(self):
        common._LAST_PRICE_INFO["MSFT.US"] = {
            "price": 483.91, "source": "pre_market", "source_label": "盘前",
            "time": datetime(2026, 11, 25, 11, 27, tzinfo=timezone.utc), "regular_price": 496.13,
        }
        with patch.object(opt_vol, "get_underlying_price", return_value=483.91), \
             patch.object(opt_vol, "get_option_expirations", return_value=self.EXPIRIES), \
             patch.object(opt_vol, "get_option_chain", side_effect=lambda u, e: self.CHAINS[e]), \
             patch.object(opt_vol, "get_kline_adjusted", side_effect=lambda s, count: self._closes(count)) as mock_kl, \
             patch.object(opt_vol, "days_to_years", side_effect=lambda e: self.DAYS[e] / 365), \
             patch.object(common, "days_to_years", side_effect=lambda e: self.DAYS[e] / 365):
            res, _ = _capture(opt_vol.analyze, "MSFT.US", output_json=False)
        self.assertEqual(res["expiry"], "2026-12-31")
        self.assertEqual(res["atm_reference_price"], 496.13)
        self.assertAlmostEqual(res["iv_pct"], 24.0)  # 按常规收盘 496.13 选到 495 档(0.24), 非盘前 485 档(0.31)
        self.assertTrue(mock_kl.called)

    def test_dashboard_options_dimension_recovers_iv_hv_when_nearest_chain_empty(self):
        seen = []
        with patch.object(dashboard, "get_option_volume_realtime", return_value={"pc_ratio": 0.68}), \
             patch.object(dashboard, "get_option_expirations", return_value=self.EXPIRIES), \
             patch.object(dashboard, "get_option_chain",
                          side_effect=lambda u, e: seen.append(e) or self.CHAINS[e]), \
             patch.object(dashboard, "get_kline_adjusted", side_effect=lambda s, count: self._closes(count)), \
             patch.object(dashboard, "days_to_years", side_effect=lambda e: self.DAYS[e] / 365), \
             patch.object(common, "days_to_years", side_effect=lambda e: self.DAYS[e] / 365):
            common._LAST_PRICE_INFO["MSFT.US"] = {"source": "pre_market", "regular_price": 496.13, "price": 483.91}
            score, detail = dashboard._dim_options("MSFT.US", [], [], price=483.91)
        self.assertEqual(seen[:2], ["2027-01-08", "2026-12-31"])
        self.assertIn("IV/HV", detail)
        self.assertIsNotNone(score)


# --------------------------------------------------------------------------- #
# 3. 节假日 / 延长时段 / VWAP / 异动 / Expected Move
# --------------------------------------------------------------------------- #

class TestHolidayAndExtendedSession(_PriceCacheCase):
    def test_us_market_holidays_and_thanksgiving_session_state(self):
        self.assertTrue(common.us_market_holiday(date(2026, 11, 26)))   # 感恩节
        self.assertFalse(common.us_market_holiday(date(2026, 11, 27)))  # 半日市非全日休市
        self.assertTrue(common.us_market_holiday(date(2026, 12, 25)))   # 圣诞
        self.assertTrue(common.us_market_holiday(date(2026, 4, 3)))     # Good Friday
        self.assertTrue(common.us_market_holiday(date(2026, 7, 3)))     # 7/4 周六补休
        self.assertTrue(common.us_market_holiday(date(2027, 1, 1)))

        # 周三 2026-11-25 18:00 ET 盘后报价, 在感恩节周四 2026-11-26 10:30 ET 与 18:00 ET 仍应作为最新价保留
        wed_post = datetime(2026, 11, 25, 18, 0, tzinfo=EST).astimezone(timezone.utc)
        quote = {
            "symbol": "MSFT.US", "market": "US", "regular_price": 496.13,
            "extended": [{"source": "post_market", "source_label": "盘后",
                          "price": 498.50, "time": wed_post}],
        }
        for hr in (10, 18):
            in_sess, last_close = common._regular_session_state(
                "US", datetime(2026, 11, 26, hr, 30, tzinfo=EST), quote["extended"])
            self.assertFalse(in_sess)
            self.assertEqual(last_close.date(), date(2026, 11, 25))
            px, info = common.latest_underlying_price(quote, now=datetime(2026, 11, 26, hr, 30, tzinfo=EST))
            self.assertEqual((px, info["source"]), (498.50, "post_market"))

        # 半日市 2026-11-27 13:05 ET 已收盘
        in_half, _ = common._regular_session_state(
            "US", datetime(2026, 11, 27, 13, 5, tzinfo=EST), [])
        self.assertFalse(in_half)

    def test_regular_session_price_reuses_cache_without_cli_call(self):
        common._LAST_PRICE_INFO["MSFT.US"] = {
            "price": 483.91, "source": "pre_market", "regular_price": 496.13,
        }
        with patch.object(common, "run_cli", side_effect=AssertionError("不应重复调 CLI")):
            self.assertEqual(common.regular_session_price("MSFT.US", 483.91), 496.13)

    def test_vwap_labels_prior_session_in_premarket_and_supports_all_session(self):
        prior_rows = [
            {"time": "2026-11-24T14:30:00Z", "price": 494.0, "avg_price": 493.5},
            {"time": "2026-11-24T20:59:00Z", "price": 496.13, "avg_price": 495.11},
        ]
        with patch.object(vwap, "get_intraday", return_value=prior_rows), \
             patch.object(common, "market_date", side_effect=lambda sym, dt=None: (
                 dt.astimezone(EST).date() if dt is not None else date(2026, 11, 25))):
            res, out = _capture(vwap.analyze, "MSFT.US", output_json=False)
        self.assertTrue(res["is_prior_session"])
        self.assertEqual(res["date"], "2026-11-24")
        self.assertIn("上一交易日常规时段", out)
        self.assertIn("--session all", out)

        with patch.object(vwap, "get_intraday", return_value=prior_rows) as mock_intraday, \
             patch.object(common, "market_date", return_value=date(2026, 11, 24)):
            res_all, out_all = _capture(vwap.analyze, "MSFT.US", session="all", output_json=False)
        self.assertEqual(res_all["session"], "all")
        self.assertEqual(mock_intraday.call_args.kwargs.get("session"), "all")
        self.assertIn("含延长时段", out_all)

    def test_anomaly_score_reflects_premarket_drop(self):
        msft_quote = [{
            "symbol": "MSFT.US", "last": "496.130", "prev_close": "492.500", "change_percentage": "0.74",
            "pre_market": {
                "last": "483.910", "prev_close": "496.130",
                "timestamp": "2026-11-25T11:27:51Z", "volume": 84200,
            },
        }]
        with patch.object(common, "run_cli", return_value=msft_quote), \
             patch.object(common, "market_now", return_value=datetime(2026, 11, 25, 6, 28, tzinfo=EST)), \
             patch.object(anomaly, "get_anomaly", return_value={"changes": []}), \
             patch.object(anomaly, "get_capital_flow_snapshot", return_value={}), \
             patch.object(anomaly, "get_top_movers", return_value={"events": []}):
            res, out = _capture(anomaly.calc_score, "MSFT.US", market="US", output_json=False)
        chg = res["dimensions"]["change"]
        self.assertEqual(chg["direction"], "下跌")
        self.assertAlmostEqual(chg["change_pct"], -2.4631, places=2)
        self.assertIn("下跌 (-2.46%", out)
        self.assertIn("盘前价", out)

    def test_expected_move_and_term_structure_pick_atm_using_regular_price(self):
        # 模拟 MSFT 盘前 483.91 对常规收盘 496.13: 485C last=11.83(实值), 495 Straddle=2.50+2.10=4.60
        chain = [
            {"strike": 485.0, "call_last": 11.43, "put_last": 0.40, "call_iv": 0.29, "put_iv": 0.28, "standard": "true"},
            {"strike": 495.0, "call_last": 2.50, "put_last": 2.10, "call_iv": 0.24, "put_iv": 0.24, "standard": "true"},
        ]
        common._LAST_PRICE_INFO["MSFT.US"] = {
            "price": 483.91, "source": "pre_market", "source_label": "盘前",
            "time": datetime(2026, 11, 25, 11, 27, tzinfo=timezone.utc), "regular_price": 496.13,
        }
        with patch.object(expected_move, "get_underlying_price", return_value=483.91), \
             patch.object(expected_move, "get_option_expirations", return_value=["2026-11-25"]), \
             patch.object(expected_move, "get_option_chain", return_value=chain), \
             patch.object(expected_move, "days_to_years", return_value=0.4 / 365):
            em_res, em_out = _capture(expected_move.analyze, "MSFT.US", output_json=False)
        self.assertEqual(em_res["main"]["atm_strike"], 495.0)
        self.assertEqual(em_res["chain_reference_price"], 496.13)
        self.assertAlmostEqual(em_res["main"]["straddle_cost"], 4.60, places=2)
        self.assertIn("按常规时段收盘价选取", em_out)

        with patch.object(term_struct, "get_underlying_price", return_value=483.91), \
             patch.object(term_struct, "get_option_expirations", return_value=["2026-11-25", "2026-12-04"]), \
             patch.object(term_struct, "get_option_chain", return_value=chain), \
             patch.object(term_struct, "days_to_years", side_effect=[1 / 365, 9 / 365]):
            ts_res, _ = _capture(term_struct.analyze, "MSFT.US", count=2, output_json=False)
        self.assertEqual(ts_res["atm_reference_price"], 496.13)
        self.assertEqual(ts_res["term_structure"][0]["atm_strike"], 495.0)


# --------------------------------------------------------------------------- #
# 4. 多点号代码 / 窄止损告警 / 仪表盘展示 / screener --count
# --------------------------------------------------------------------------- #

class TestGroup4Polish(_PriceCacheCase):
    def test_multi_dot_and_single_letter_tickers(self):
        # BRK.B.US 与 BRK.A.US 区分; 单字母 A.US 不被误匹配 AAPL
        with patch.object(val_pctl, "get_valuation", return_value={
            "history": {"metrics": {"pe": {"circle": "20", "list": [{"value": "18"}, {"value": "22"}]}}},
            "peers": {"pe": {"list": [
                {"counter_id": "ST/US/AAPL", "name": "Apple", "value": "35"},
                {"counter_id": "ST/US/BRK.A", "name": "Berkshire A", "value": "21"},
                {"counter_id": "ST/US/BRK.B", "name": "Berkshire B", "value": "20"},
            ]}},
        }), patch.object(val_pctl, "get_industry_valuation_dist", return_value={}):
            r_a = val_pctl.analyze("A.US", quiet=True)
            r_brk = val_pctl.analyze("BRK.B.US", quiet=True)
        self.assertFalse(any(p["is_target"] for p in r_a["peers"]["list"]))
        flags = {p["symbol"]: p["is_target"] for p in r_brk["peers"]["list"]}
        self.assertTrue(flags["BRK.B.US"])
        self.assertFalse(flags["BRK.A.US"])

        with patch.object(entry, "get_heat_rank_keys", return_value=[{"key": "hot_all-us"}]), \
             patch.object(entry, "get_heat_rank", return_value={"lists": [{"symbol": "BRK.A.US"}]}):
            self.assertFalse(entry._in_heat_rank("BRK.B.US"))
        with patch.object(entry, "get_heat_rank_keys", return_value=[{"key": "hot_all-us"}]), \
             patch.object(entry, "get_heat_rank", return_value={"lists": [{"symbol": "BRK.B.US"}]}):
            self.assertTrue(entry._in_heat_rank("BRK.B.US"))

        with patch.object(iv_crush, "get_finance_calendar", return_value=[{
            "infos": [{"counter_id": "ST/US/BRK.B", "date": "2027-02-20", "data_kv": []}],
        }]), patch.object(iv_crush, "market_date", return_value=date(2026, 11, 25)):
            self.assertIsNotNone(iv_crush.find_next_earnings("BRK.B.US"))

        with patch.object(dividend, "get_dividend_history", return_value=[
            {"ex_date": "2026.05.10", "amount": 0.5, "currency": "USD"},
        ]), patch.object(dividend, "get_underlying_price", return_value=100.0), \
             patch.object(dividend, "market_date", return_value=date(2026, 11, 25)):
            self.assertEqual(dividend.analyze("BRK.B.US", quiet=True)["quote_currency"], "USD")

    def test_entry_rules_premarket_breach_stop_and_min_stop_pct(self):
        # 复现 MSFT.US: 常规收盘 496.13, 建议止损 490.29, 盘前价 483.92 已跌破止损
        note = entry._price_note(
            {"source": "pre_market", "source_label": "盘前", "price": 483.92,
             "time": datetime(2026, 11, 25, 11, 28, tzinfo=timezone.utc)},
            stop=490.29,
        )
        self.assertIn("延长时段最新价 483.92", note)
        self.assertIn("已跌破建议止损 490.29", note)

        bars = [{"open": 100.0, "close": 100.0, "high": 102.0, "low": 98.0, "volume": 1_000_000}
                for _ in range(40)]
        f = entry.build_features(bars)
        f["stop"], f["target"] = 99.5, 105.0  # 0.5% 极窄止损 vs ATR~4%
        r_default = entry.check_rules(f, {"max_stop_pct": 8.0})
        self.assertEqual(r_default["rules"]["D5"]["status"], "clear")
        self.assertIn("小于 0.5×ATR", r_default["rules"]["D5"]["evidence"])

        r_min = entry.check_rules(f, {"max_stop_pct": 8.0, "min_stop_pct": 1.0})
        self.assertEqual(r_min["rules"]["D5"]["status"], "triggered")
        self.assertIn("低于最小止损下限 1%", r_min["rules"]["D5"]["evidence"])

    def test_dashboard_formatting_and_screener_count(self):
        with patch.object(dashboard, "analyst_analyze", return_value={
            "rating": {"buy": 40, "over": 15, "hold": 3, "under": 0, "sell": 0, "total": 58,
                       "label": "🟢 强烈看多"},
            "target_price": {"upside_to_mid_pct": 31.7},
        }):
            bulls, bears = [], []
            dashboard._dim_analyst("MSFT.US", bulls, bears)
        self.assertEqual(bulls[0], "分析师: 强烈看多(55/58 家看多)")

        with patch.object(common, "run_cli", return_value={"items": [{"symbol": "A.US"}]}) as mock_cli:
            screener.fetch_screener(conditions=["roe:20:"], market="US", count=5, output_json=True)
        self.assertIn("--count", mock_cli.call_args.args)
        self.assertIn("5", mock_cli.call_args.args)


if __name__ == "__main__":
    unittest.main()
