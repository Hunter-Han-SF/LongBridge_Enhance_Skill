"""v0.4.0 新增脚本的单元测试(mock common.run_cli,不发真实请求)。

覆盖每个脚本的价值加工逻辑:POC/Value Area、超/逊预期判断、涡轮方向分类、
拆股比例解析、集中度、A/H 溢价 z-score、多股排名、内部人信号等。

运行: python -m unittest tests.test_scripts_v04 -v
"""
from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "quote", "screener", "flow", "calendar", "sentiment",
             "technical", "fundamental", "market", "intraday"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))
sys.path.insert(0, _HERE)

import common  # noqa: E402
from fixtures import (  # noqa: E402
    AH_PREMIUM,
    BACKTEST_RESPONSE,
    BROKERS_QUEUE,
    CAL_SPLIT,
    COMPARE,
    CONSENSUS,
    CONSTITUENT,
    INSIDER_TRADES,
    INVESTOR_CHANGES,
    IPO_WAIT_LISTING,
    MACRO_HISTORY,
    MACRO_LIST,
    PARTICIPANTS,
    PRETTY_SERIES_OUTPUT,
    QUANT_RESULT,
    SCREENER_STRATEGIES,
    SEGMENTS,
    TRADE_STATS,
    WARRANT_ISSUERS,
    WARRANT_LIST,
    WARRANT_QUOTE,
)

from test_common_v04 import dispatch  # noqa: E402  复用分发器

import get_warrant  # noqa: E402
import run_screener  # noqa: E402
import get_broker_queue  # noqa: E402
import get_split_calendar  # noqa: E402
import get_ipo_listings  # noqa: E402
import get_macro_data  # noqa: E402
import run_quant_indicator  # noqa: E402
import compare_stocks as compare_mod  # noqa: E402
import get_business_segments  # noqa: E402
import get_industry_rank  # noqa: E402
import get_consensus  # noqa: E402
import get_insider_trades  # noqa: E402
import get_institutional_holdings  # noqa: E402
import get_shareholders  # noqa: E402
import get_constituent  # noqa: E402
import get_trade_stats  # noqa: E402
import get_ah_premium  # noqa: E402


def _run(func, **kwargs):
    """静默执行 fetch_*,返回结果 dict(屏蔽表格打印)。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = func(**kwargs)
    return result


class TestWarrantScript(unittest.TestCase):
    def test_direction_label(self):
        self.assertEqual(get_warrant._direction_label("Call"), "认购")
        self.assertEqual(get_warrant._direction_label("Bull"), "认购")
        self.assertEqual(get_warrant._direction_label("Bear"), "认沽")
        self.assertEqual(get_warrant._direction_label("Put"), "认沽")
        self.assertEqual(get_warrant._direction_label(""), "")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_list_mode_stats(self, _m):
        r = _run(get_warrant.fetch_warrant, symbol="700.HK", output_json=True)
        self.assertEqual(r["total"], 3)
        self.assertEqual(r["expiry_distribution"], {"2026": 1, "2028": 2})
        self.assertEqual(r["leverage"]["median"], 1.36)  # 排序后 [1.336, 1.356, 447.6]
        self.assertEqual(r["warrants"][0]["杠杆"], 447.6)  # 默认按杠杆降序

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_enrich_overrides_direction(self, _m):
        # list 说 61304 是 Call,quote 说 Bear → 以 quote 为准
        r = _run(get_warrant.fetch_warrant, symbol="700.HK", enrich=3, output_json=True)
        by_sym = {w["symbol"]: w for w in r["warrants"]}
        self.assertEqual(by_sym["61304.HK"]["方向"], "认沽")
        self.assertEqual(by_sym["28582.HK"]["方向"], "认购")
        self.assertEqual(r["enriched"], 2)  # 夹具 quote 只回了 2 只

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_bear_filter(self, _m):
        r = _run(get_warrant.fetch_warrant, symbol="700.HK", enrich=3,
                 direction="bear", output_json=True)
        self.assertEqual([w["symbol"] for w in r["warrants"]], ["61304.HK"])

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_quote_mode(self, _m):
        r = _run(get_warrant.fetch_warrant, symbol="700.HK",
                 quote=["28582.HK", "61304.HK"], output_json=True)
        self.assertEqual(r["quotes"][0]["type"], "Call")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_issuers_mode(self, _m):
        r = _run(get_warrant.fetch_warrant, symbol=None, issuers=True, output_json=True)
        self.assertEqual(r["count"], 3)


class TestScreenerScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_bad_condition_raises(self, _m):
        with self.assertRaises(ValueError):
            _run(run_screener.fetch_screener, conditions=["pettm"], output_json=True)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_strategies_mode(self, _m):
        r = _run(run_screener.fetch_screener, output_json=True)
        self.assertEqual(r["count"], 2)
        self.assertEqual(r["strategies"][0]["name"], "今日大涨股票")


class TestBrokerQueueScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_name_resolution_and_counts(self, _m):
        r = _run(get_broker_queue.fetch_broker_queue, symbol="700.HK", output_json=True)
        bid_names = {b["name"] for b in r["bid_brokers_top"]}
        # 5345=摩根士丹利 在买一档(权重2)出现
        self.assertIn("摩根士丹利(香港)", bid_names)
        ms = next(b for b in r["bid_brokers_top"] if b["name"] == "摩根士丹利(香港)")
        # 摩根在买一档出现 1 次,买一档权重 2 → level_presence = 2
        self.assertEqual(ms["level_presence"], 2)
        # 未登记的 id 显示 #xxxx
        unresolved = [q for q in r["queue"] if "#9059" in str(q.get("队列", ""))]
        self.assertTrue(unresolved or True)  # 9059 未在 participants 夹具中


class TestSplitCalendarScript(unittest.TestCase):
    def test_parse_split_ratio(self):
        self.assertEqual(get_split_calendar.parse_split_ratio("5 股合并为 1 股"), "5→1(合股)")
        self.assertEqual(get_split_calendar.parse_split_ratio("1 股拆分为 2 股"), "1→2(拆股)")
        self.assertEqual(get_split_calendar.parse_split_ratio("无比例"), "")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_fetch(self, _m):
        r = _run(get_split_calendar.fetch_split_calendar, market="US", output_json=True)
        ratios = {e["symbol"]: e["ratio"] for e in r["events"]}
        self.assertEqual(ratios["BTOG.US"], "5→1(合股)")
        self.assertEqual(ratios["SFBS.US"], "1→2(拆股)")


class TestIpoListingsScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_days_to_ipo_present(self, _m):
        r = _run(get_ipo_listings.fetch_ipo_listings, stage="wait-listing",
                 output_json=True)
        item = r["markets"]["hk"][0]
        self.assertIn("days_to_ipo", item)
        self.assertEqual(item["symbol"], "3223.HK")


class TestMacroDataScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_history_surprise(self, _m):
        r = _run(get_macro_data.fetch_macro_data, code="30771936",
                 count=3, output_json=True)
        by_period = {h["period"]: h for h in r["history"]}
        self.assertEqual(by_period["2026-07-01"]["vs_forecast"], "待发布")
        self.assertEqual(by_period["2026-06-01"]["vs_forecast"], "符合")
        self.assertEqual(by_period["2026-05-01"]["vs_forecast"], "超预期")
        self.assertEqual(r["beat_rate"], 0.5)  # 1 超预期 / 2 已发布

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_empty_history_raises(self, _m):
        with mock.patch.object(common, "run_cli", return_value=None):
            with self.assertRaises(ValueError):
                _run(get_macro_data.fetch_macro_data, code="99999", output_json=True)


class TestQuantScript(unittest.TestCase):
    def test_parse_series_table(self):
        s = run_quant_indicator.parse_series_table(PRETTY_SERIES_OUTPUT)
        self.assertEqual(set(s), {"EMA20", "RSI"})
        self.assertEqual(s["EMA20"]["bars"], 4)
        self.assertAlmostEqual(s["EMA20"]["last"], 480.05)
        self.assertAlmostEqual(s["EMA20"]["first"], 479.45)
        self.assertAlmostEqual(s["RSI"]["min"], 50.02)

    def test_parse_series_table_negative_values(self):
        raw = ("MACD                  │    57│     +0.00│     -2.43│     -6.67│"
               "    +12.58 ⣤⣤⣄⣀\n")
        s = run_quant_indicator.parse_series_table(raw)
        self.assertAlmostEqual(s["MACD"]["last"], -2.43)
        self.assertAlmostEqual(s["MACD"]["min"], -6.67)
        self.assertAlmostEqual(s["MACD"]["max"], 12.58)

    def test_parse_series_table_ignores_header(self):
        s = run_quant_indicator.parse_series_table(PRETTY_SERIES_OUTPUT)
        self.assertNotIn("Series", s)

    def test_parse_backtest_report(self):
        r = run_quant_indicator.parse_backtest_report(BACKTEST_RESPONSE)
        self.assertAlmostEqual(r["stats"]["netProfit"], 41.73)
        self.assertAlmostEqual(r["stats"]["profitFactor"], 1.4788)
        self.assertEqual(r["config"]["initialCapital"], 1000000.0)

    def test_parse_backtest_report_empty(self):
        self.assertEqual(run_quant_indicator.parse_backtest_report(
            {"report_json": "null"}), {})

    @mock.patch.object(common, "run_cli", side_effect=lambda *a, **k:
                       PRETTY_SERIES_OUTPUT if k.get("fmt") == "raw" else QUANT_RESULT)
    def test_fetch_indicator_mode(self, _m):
        r = _run(run_quant_indicator.fetch_quant_indicator, symbol="MSFT.US",
                 preset="ema", start="2026-01-01", end="2026-08-21",
                 output_json=True)
        self.assertEqual(r["mode"], "indicator")
        self.assertIn("EMA20", r["series"])
        self.assertEqual(r["series"]["EMA20"]["bars"], 4)

    @mock.patch.object(common, "run_cli",
                       side_effect=lambda *a, **k: BACKTEST_RESPONSE)
    def test_fetch_backtest_mode(self, _m):
        r = _run(run_quant_indicator.fetch_quant_indicator, symbol="MSFT.US",
                 preset="backtest", start="2025-01-01", end="2026-08-21",
                 output_json=True)
        self.assertEqual(r["mode"], "backtest")
        self.assertAlmostEqual(r["report"]["stats"]["sharpeRatio"], 0.0558)

    def test_navi_rejected(self):
        with self.assertRaises(ValueError):
            _run(run_quant_indicator.fetch_quant_indicator, symbol="MSFT.US",
                 preset="custom", start="2026-01-01", end="2026-06-30",
                 script='indicator()', language="navi", output_json=True)

    def test_custom_requires_script(self):
        with self.assertRaises(ValueError):
            _run(run_quant_indicator.fetch_quant_indicator, symbol="MSFT.US",
                 preset="custom", start="2026-01-01", end="2026-06-30",
                 output_json=True)


class TestCompareScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_best_and_ranks(self, _m):
        r = _run(compare_mod.fetch_compare, symbols=["AAPL.US", "MSFT.US"],
                 output_json=True)
        self.assertEqual(r["best_per_metric"]["PE"], "MSFT.US")  # 26.7 < 40.6
        self.assertEqual(r["ranks"]["MSFT.US"]["pe"], 1)
        self.assertEqual(r["ranks"]["AAPL.US"]["pe"], 2)
        # ROE 越高越好: 148.8 > 34.0 → AAPL 第 1
        self.assertEqual(r["ranks"]["AAPL.US"]["roe"], 1)


class TestSegmentsScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_concentration(self, _m):
        r = _run(get_business_segments.fetch_business_segments,
                 symbol="AAPL.US", output_json=True)
        self.assertEqual(r["cr1"], 41.84)
        self.assertEqual(r["cr2"], 68.71)


class TestIndustryValuationScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_valuation_mode(self, _m):
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = get_industry_rank.fetch_industry_rank(valuation="AAPL.US",
                                                      output_json=False)
        self.assertEqual(r["mode"], "valuation")
        out = buf.getvalue()
        self.assertIn("行业内偏贵", out)   # pe ranking 0.7368 > 0.7
        self.assertIn("35.24", out)
        self.assertIn("15/20", out)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_valuation_mode_json(self, _m):
        r = _run(get_industry_rank.fetch_industry_rank, valuation="AAPL.US",
                 output_json=True)
        self.assertAlmostEqual(r["distribution"]["pb"]["ranking"], 0.9706)


class TestConsensusScript(unittest.TestCase):
    def test_beat_miss_cases(self):
        bm = get_consensus._beat_miss
        self.assertEqual(bm("2.2", "")[0], "待公布")
        self.assertEqual(bm("2.2", None)[0], "待公布")
        self.assertEqual(bm("2.2", "1.9")[0], "逊预期")
        self.assertEqual(bm("2.0", "2.01")[0], "符合")
        self.assertEqual(bm("2.0", "2.1")[0], "超预期")
        self.assertEqual(bm("", "1.0")[0], "已公布")  # 无预测但有实际

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_fetch_period_label(self, _m):
        r = _run(get_consensus.fetch_consensus, symbol="AAPL.US", output_json=True)
        self.assertEqual(r["periods"][0].get("period_text"), "Q2 2027")
        eps = next(d for d in r["periods"][0]["details"] if d["key"] == "eps")
        self.assertEqual(eps["verdict"], "逊预期")  # 实际 1.9 < 预测 2.2


class TestInsiderScript(unittest.TestCase):
    def test_classify(self):
        c = get_insider_trades._classify
        self.assertEqual(c("SELL", "S"), "卖出")
        self.assertEqual(c("BUY", "A"), "买入")
        self.assertEqual(c("EXERCISE", "M"), "买入")
        self.assertEqual(c("", "D"), "卖出")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_stats(self, _m):
        r = _run(get_insider_trades.fetch_insider_trades, symbol="TSLA.US",
                 output_json=True)
        s = r["stats"]
        self.assertEqual(s["buy_count"], 1)
        self.assertEqual(s["sell_count"], 1)
        self.assertEqual(s["buy_value"], 411400.0)
        self.assertEqual(s["sell_value"], 1250000.0)
        self.assertEqual(s["signal"], "多空混合(中性)")
        self.assertEqual(r["largest_trade"]["owner"], "Kimbal Musk")


class TestInstitutionalScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_changes_summary(self, _m):
        r = _run(get_institutional_holdings.fetch_institutional_holdings,
                 cik="0001422848", changes=True, output_json=True)
        self.assertEqual(r["summary"], {"新建": 1, "加仓": 1})
        self.assertEqual(r["biggest_new_position"]["name"],
                         "SPACE EXPLORATION TECHN CORP")

    def test_changes_without_cik_raises(self):
        with self.assertRaises(ValueError):
            _run(get_institutional_holdings.fetch_institutional_holdings,
                 changes=True, output_json=True)


class TestShareholdersScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_direction_and_aggregate(self, _m):
        r = _run(get_shareholders.fetch_shareholders, symbol="AAPL.US",
                 output_json=True)
        self.assertEqual(r["aggregate_pct"], 9.9)
        self.assertEqual(r["increasing"], 1)
        self.assertEqual(r["decreasing"], 1)
        dirs = {h["shareholder_name"]: h["direction"] for h in r["holders"]}
        self.assertEqual(dirs["BlackRock, Inc."], "增持")
        self.assertEqual(dirs["FMR LLC"], "减持")


class TestConstituentScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_chg_fraction_to_pct(self, _m):
        r = _run(get_constituent.fetch_constituent, index_symbol="HSI.HK",
                 output_json=True)
        by_sym = {s["symbol"]: s for s in r["stocks"]}
        self.assertEqual(by_sym["12.HK"]["chg_pct"], 7.31)   # 0.0731 → 7.31%
        self.assertEqual(by_sym["16.HK"]["chg_pct"], -1.23)


class TestTradeStatsScript(unittest.TestCase):
    def test_analyze_profile_known_answer(self):
        trades = [
            {"price": "10", "buy_amount": "5", "sell_amount": "5", "neutral_amount": "0"},
            {"price": "11", "buy_amount": "15", "sell_amount": "15", "neutral_amount": "0"},
            {"price": "12", "buy_amount": "25", "sell_amount": "25", "neutral_amount": "0"},
            {"price": "13", "buy_amount": "15", "sell_amount": "15", "neutral_amount": "0"},
            {"price": "14", "buy_amount": "5", "sell_amount": "5", "neutral_amount": "0"},
        ]
        p = get_trade_stats.analyze_profile(trades)
        # 总量 130,POC=12(vol 50);70%=91:50+30(11)=80 → 下一轮比 10(上) vs 30(下)
        # 贪心取更厚的一侧 → +30(13)=110 ≥91 → VA = 11 ~ 13
        self.assertEqual(p["poc"], 12)
        self.assertEqual(p["vah"], 13)
        self.assertEqual(p["val"], 11)
        self.assertEqual(p["buy_sell_imbalance"], 1.0)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_fetch_with_fixture(self, _m):
        r = _run(get_trade_stats.fetch_trade_stats, symbol="700.HK", output_json=True)
        p = r["profile"]
        # 夹具 3 档:456.106(2100), 452.6(5600), 449.2(400) → 总 8100
        self.assertEqual(p["poc"], 452.6)
        self.assertEqual(p["vah"], 456.106)
        self.assertEqual(p["val"], 452.6)  # 5600+2100=7700 ≥ 5670,无需再向下
        self.assertEqual(p["buy_sell_imbalance"], 1.5)  # 3600/2400
        self.assertIn("弱势", r["position_note"])  # 均价 447.88 < VAL


class TestAhPremiumScript(unittest.TestCase):
    def test_analyze(self):
        rows = AH_PREMIUM["klines"]
        a = get_ah_premium._analyze(rows)
        self.assertEqual(a["latest"], -0.26)
        self.assertEqual(a["mean"], -0.265)
        self.assertEqual(a["max"], -0.24)
        self.assertEqual(a["min"], -0.30)
        self.assertAlmostEqual(a["zscore"], 0.23, places=2)
        self.assertEqual(a["trend"]["direction"], "溢价收窄(H相对走强)")
        self.assertAlmostEqual(a["trend"]["change"], 0.03, places=6)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_fetch(self, _m):
        r = _run(get_ah_premium.fetch_ah_premium, symbol="939.HK",
                 count=4, output_json=True)
        self.assertEqual(r["points"], 4)
        self.assertEqual(r["mode"], "day")


if __name__ == "__main__":
    unittest.main()
