"""common.py v0.4.0 新增封装函数的单元测试(mock run_cli,不发真实请求)。

运行: python -m unittest tests.test_common_v04 -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "scripts")))
sys.path.insert(0, os.path.dirname(__file__))

import common  # noqa: E402
from fixtures import (  # noqa: E402
    AH_PREMIUM,
    AH_PREMIUM_INTRADAY,
    BROKERS_QUEUE,
    CAL_SPLIT,
    COMPARE,
    CONSENSUS,
    CONSTITUENT,
    CORP_ACTIONS,
    EXECUTIVES,
    FUND_HOLDERS,
    INDUSTRY_PEERS,
    INDUSTRY_RANK,
    INDUSTRY_VALUATION_DIST,
    INSIDER_TRADES,
    INVESTOR_CHANGES,
    INVESTOR_HOLDINGS,
    INVESTOR_RANKINGS,
    IPO_DETAIL,
    IPO_SUBSCRIPTIONS,
    IPO_WAIT_LISTING,
    MACRO_HISTORY,
    MACRO_LIST,
    OPERATING,
    PARTICIPANTS,
    QUANT_RESULT,
    SCREENER_FILTER,
    SCREENER_INDICATORS,
    SCREENER_RUN,
    SCREENER_STRATEGIES,
    SEGMENTS,
    SHAREHOLDERS,
    TRADE_STATS,
    WARRANT_ISSUERS,
    WARRANT_LIST,
    WARRANT_QUOTE,
    COMPANY,
)


def dispatch(*args, **kwargs):
    """按子命令序列分发夹具。mock side_effect 按 *args/**kwargs 展开调用。"""
    a = [str(x) for x in args]
    if a[:2] == ["warrant", "quote"]:
        return WARRANT_QUOTE
    if a[:2] == ["warrant", "issuers"]:
        return WARRANT_ISSUERS
    if a[:1] == ["warrant"] and len(a) == 2:
        return WARRANT_LIST
    if a[:2] == ["screener", "strategies"]:
        return SCREENER_STRATEGIES
    if a[:2] == ["screener", "run"]:
        return SCREENER_RUN
    if a[:2] == ["screener", "filter"]:
        return SCREENER_FILTER
    if a[:2] == ["screener", "indicators"]:
        return SCREENER_INDICATORS
    if a[:1] == ["brokers"]:
        return BROKERS_QUEUE
    if a[:1] == ["participants"]:
        return PARTICIPANTS
    if a[:2] == ["finance-calendar", "split"]:
        return CAL_SPLIT
    if a[:2] == ["finance-calendar", "ipo"]:
        return {"date": "2026-08-21", "list": []}
    if a[:2] == ["finance-calendar", "macrodata"]:
        return CAL_SPLIT  # 结构同 split,足够测
    if a[:2] == ["finance-calendar", "closed"]:
        return CAL_SPLIT
    if a[:2] == ["ipo", "wait-listing"]:
        return IPO_WAIT_LISTING
    if a[:2] == ["ipo", "subscriptions"]:
        return IPO_SUBSCRIPTIONS
    if a[:2] == ["ipo", "detail"]:
        return IPO_DETAIL
    if a[:1] == ["macrodata"] and len(a) > 1 and a[1].isdigit():
        return MACRO_HISTORY
    if a[:1] == ["macrodata"]:
        return MACRO_LIST
    if a[:2] == ["quant", "run"]:
        return QUANT_RESULT
    if a[:1] == ["compare"]:
        return COMPARE
    if a[:1] == ["business-segments"]:
        return SEGMENTS
    if a[:1] == ["industry-rank"]:
        return INDUSTRY_RANK
    if a[:2] == ["industry-valuation", "dist"]:
        return INDUSTRY_VALUATION_DIST
    if a[:1] == ["industry-valuation"]:
        return COMPARE
    if a[:1] == ["industry-peers"]:
        return INDUSTRY_PEERS
    if a[:1] == ["consensus"]:
        return CONSENSUS
    if a[:1] == ["corp-action"]:
        return CORP_ACTIONS
    if a[:1] == ["operating"]:
        return OPERATING
    if a[:1] == ["company"]:
        return COMPANY
    if a[:1] == ["executive"]:
        return EXECUTIVES
    if a[:1] == ["insider-trades"]:
        return INSIDER_TRADES
    if a[:1] == ["investors"] and "changes" in a:
        return INVESTOR_CHANGES
    if a[:1] == ["investors"] and len(a) == 2:
        return INVESTOR_HOLDINGS
    if a[:1] == ["investors"]:
        return INVESTOR_RANKINGS
    if a[:1] == ["fund-holder"]:
        return FUND_HOLDERS
    if a[:1] == ["shareholder"]:
        return SHAREHOLDERS
    if a[:1] == ["constituent"]:
        return CONSTITUENT
    if a[:1] == ["trade-stats"]:
        return TRADE_STATS
    if a[:2] == ["ah-premium", "intraday"]:
        return AH_PREMIUM_INTRADAY
    if a[:1] == ["ah-premium"]:
        return AH_PREMIUM
    raise AssertionError(f"测试未覆盖的 CLI 调用: {a}")


class TestWarrant(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_list_normalizes_floats(self, _m):
        rows = common.get_warrant_list("700.HK")
        self.assertEqual(len(rows), 3)
        self.assertIsInstance(rows[0]["leverage_ratio"], float)
        self.assertEqual(rows[0]["symbol"], "61304.HK")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_quote_single_call_with_all_symbols(self, _m):
        with mock.patch.object(common, "run_cli", wraps=None) as spy:
            spy.side_effect = dispatch
            rows = common.get_warrant_quote(["28582.HK", "61304.HK"])
            self.assertEqual(len(rows), 2)
            spy.assert_called_once_with("warrant", "quote", "28582.HK", "61304.HK")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_issuers(self, _m):
        rows = common.get_warrant_issuers()
        self.assertEqual(rows[0]["name_cn"], "法兴")


class TestScreener(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_strategies(self, _m):
        rows = common.get_screener_strategies()
        self.assertEqual(rows[0]["id"], 19)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_run_strategy_items(self, _m):
        rows = common.run_screener_strategy(27)
        self.assertEqual(rows[0]["symbol"], "2291.HK")
        self.assertIsInstance(rows[0]["marketcap"], float)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_filter_args_construction(self, _m):
        with mock.patch.object(common, "run_cli", side_effect=dispatch) as spy:
            common.screener_filter(["pettm:10:50", "roe:5:"], market="HK")
            spy.assert_called_once_with("screener", "filter", "pettm:10:50",
                                        "roe:5:", "--market", "HK")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_filter_items(self, _m):
        rows = common.screener_filter(["pettm:10:50"])
        self.assertEqual(rows[0]["symbol"], "708.HK")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_indicators(self, _m):
        rows = common.get_screener_indicators()
        self.assertEqual(rows[1]["key"], "marketcap")


class TestBrokersAndParticipants(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_broker_queue_shape(self, _m):
        q = common.get_broker_queue("700.HK")
        self.assertEqual(q["asks"][0]["position"], 1)
        self.assertEqual(len(q["bids"][0]["broker_ids"]), 3)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_participants_splits_multi_id(self, _m):
        rows = common.get_participants()
        ids = [r["broker_id"] for r in rows]
        # "7707, 7708, 7709" 应拆成 3 条
        self.assertIn("7707", ids)
        self.assertIn("7708", ids)
        self.assertIn("7709", ids)
        name = {r["broker_id"]: r["name_cn"] for r in rows}
        self.assertEqual(name["5345"], "摩根士丹利(香港)")


class TestIpoAndCalendar(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_ipo_listings(self, _m):
        data = common.get_ipo_listings("wait-listing")
        self.assertEqual(data["hk"][0]["symbol"], "3223.HK")
        self.assertEqual(data["us"], [])

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_ipo_detail(self, _m):
        data = common.get_ipo_detail("3223.HK")
        self.assertIn("profile", data)
        self.assertEqual(data["holdings"]["finance_fee_rate"], "0.068")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_finance_calendar_split(self, _m):
        buckets = common.get_finance_calendar("split", market="US")
        self.assertEqual(buckets[0]["infos"][0]["counter_id"], "ST/US/BTOG")


class TestMacrodata(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_indicator_list(self, _m):
        data = common.get_macro_indicators(keyword="CPI", country="EU")
        # indicator_code 数值字符串会被 coerce 成 int(无前导零,传回 CLI 无碍)
        self.assertEqual(str(data["list"][0]["indicator_code"]), "30771434")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_history(self, _m):
        rows = common.get_macro_history("30771434", limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["period"], "2026-07-01")
        self.assertIsInstance(rows[0]["release_at"], int)


class TestQuantScript(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_run_requires_script(self, _m):
        with self.assertRaises(ValueError):
            common.run_quant_script("AAPL.US", "2026-01-01", "2026-06-30")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_run_args(self, _m):
        with mock.patch.object(common, "run_cli", side_effect=dispatch) as spy:
            out = common.run_quant_script("AAPL.US", "2026-01-01", "2026-06-30",
                                          script="indicator()", language="navi",
                                          script_input="[14]")
            self.assertEqual(out["series"]["EMA Fast"], [10.0, 11.0, 12.5])
            spy.assert_called_once_with(
                "quant", "run", "AAPL.US", "--start", "2026-01-01",
                "--end", "2026-06-30", "--period", "day",
                "--language", "navi", "--input", "[14]", "--script", "indicator()",
                fmt="json")


class TestFundamental(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_compare(self, _m):
        rows = common.compare_stocks(["AAPL.US", "MSFT.US"])
        self.assertEqual(len(rows), 2)
        self.assertIsInstance(rows[0]["pe"], float)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_segments(self, _m):
        rows = common.get_business_segments("AAPL.US")
        self.assertEqual(rows[0]["name"], "美洲")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_industry_rank_nested(self, _m):
        rows = common.get_industry_rank("US")
        self.assertEqual(rows[0]["lists"][0]["counter_id"], "BK/US/IN00362")
        self.assertIsInstance(rows[0]["lists"][0]["chg"], float)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_industry_peers(self, _m):
        data = common.get_industry_peers("BK/US/IN00362")
        self.assertEqual(data["top"]["name"], "工业")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_industry_valuation_dist(self, _m):
        dist = common.get_industry_valuation_dist("AAPL.US")
        self.assertAlmostEqual(dist["pe"]["median"], 10.86)
        self.assertAlmostEqual(dist["pb"]["ranking"], 0.9706)
        self.assertNotIn("ps", dist)  # 夹具只有 pe/pb,按实际返回处理

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_consensus(self, _m):
        data = common.get_consensus("AAPL.US")
        d = data["list"][0]["details"][0]
        self.assertEqual(d["name"], "营业收入")
        self.assertEqual(d["estimate"], 123287028540.0)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_corp_actions(self, _m):
        rows = common.get_corp_actions("AAPL.US")
        self.assertEqual(rows[0]["action"], "DividendExDate")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_operating(self, _m):
        rows = common.get_operating("700.HK")
        self.assertEqual(rows[0]["financial"]["indicators"][0]["indicator_name"], "营业收入")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_company_profile(self, _m):
        p = common.get_company_profile("AAPL.US")
        self.assertEqual(p["company_name"], "Apple Inc.")
        self.assertEqual(p["employees"], 166000)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_executives(self, _m):
        rows = common.get_executives("AAPL.US")
        self.assertEqual(rows[0]["professionals"][0]["name"], "Timothy D. Cook")


class TestSignals(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_insider_trades(self, _m):
        rows = common.get_insider_trades("TSLA.US", count=2)
        self.assertEqual(rows[1]["type"], "SELL")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_investor_rankings(self, _m):
        rows = common.get_investor_rankings()
        self.assertEqual(rows[0]["cik"], "0001422848")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_investor_holdings(self, _m):
        data = common.get_investor_holdings("0001422848")
        self.assertEqual(data["firm"], "Capital Research Global Investors")
        self.assertEqual(data["holdings"][0]["shares"], 113126312)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_investor_changes(self, _m):
        data = common.get_investor_changes("0001422848")
        self.assertEqual(data["added"], 2)
        self.assertEqual(data["changes"][0]["action"], "NEW")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_fund_holders(self, _m):
        rows = common.get_fund_holders("AAPL.US")
        self.assertEqual(rows[0]["code"], "AAPX")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_shareholders(self, _m):
        rows = common.get_shareholders("AAPL.US")
        self.assertEqual(rows[0]["shareholder_name"], "BlackRock, Inc.")


class TestMarketAndIntraday(unittest.TestCase):
    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_constituent_args(self, _m):
        with mock.patch.object(common, "run_cli", side_effect=dispatch) as spy:
            common.get_constituent(".SPX.US", limit=10, sort="inflow", order="asc")
            spy.assert_called_once_with("constituent", ".SPX.US", "--limit", "10",
                                        "--sort", "inflow", "--order", "asc")

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_constituent_stocks(self, _m):
        data = common.get_constituent("HSI.HK")
        self.assertEqual(data["stocks"][0]["name"], "恒基地产")
        self.assertIsInstance(data["stocks"][0]["inflow"], (int, float))

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_trade_stats(self, _m):
        data = common.get_trade_stats("700.HK")
        self.assertEqual(data["statistics"]["avgprice"], 447.88)
        self.assertEqual(len(data["trades"]), 3)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_ah_premium(self, _m):
        rows = common.get_ah_premium("939.HK", count=4)
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(rows[0]["ahpremium_rate"], -0.30)

    @mock.patch.object(common, "run_cli", side_effect=dispatch)
    def test_ah_premium_intraday(self, _m):
        rows = common.get_ah_premium_intraday("939.HK")
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
