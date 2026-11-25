"""v0.6.4 修复回归:2026-11-25 第六轮审计的低优先级项。

覆盖:
  1. 唐奇安突破信号(确认已有修复有效,新高/新低可触发)
  2. calc_gex 优先 BS gamma(避免服务端 3 位小数把虚值腿舍入为 0),native 作兜底
  3. 组合 Greeks 传导 theta_source: dead_zero/None 腿不计入,整组 theta 置 None
  4. A/H 溢价日期按港股当地时区(不再用 UTC 导致周一变周日)
  5. 估值同行排名取 industry-valuation dist 全行业排名,不再用 5 条预览充当排名
  6. Put/Call 墙回退到非预期一侧时不硬标「下方支撑」/「上方阻力」
  7. Gamma 剖面 S/R 去重间距随行权价间距中位数 h 自适应,不用绝对值 2.0
  8. 美股规则半日市(感恩节翌日/平安夜/独立日前夕)T 与未收盘 bar 按 13:00 ET 收盘
  9. 市场温度档位统一为 70/50/30(get_market_temp 与 daily_briefing 一致)
 10. 异动榜涨跌幅小数转百分比(如 -0.0831 → -8.31%)

运行: python -m unittest tests.test_fixes_v064 -v
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "fundamental", "market", "quote", "sentiment", "technical"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))

import calc_gamma_profile as cgp  # noqa: E402
import calc_gex as cgex  # noqa: E402
import calc_indicators as ci  # noqa: E402
import calc_option_greeks as cog  # noqa: E402
import common  # noqa: E402
import daily_briefing as dbf  # noqa: E402
import get_ah_premium as ahp  # noqa: E402
import get_market_temp as gmt  # noqa: E402
import get_option_oi as goi  # noqa: E402
import get_put_call_wall as gpcw  # noqa: E402
import get_top_movers as gtm  # noqa: E402
import get_valuation_percentile as gvp  # noqa: E402


def _capture(func, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = func(*args, **kwargs)
    return res, buf.getvalue()


class TestDonchianSignalConfirmed(unittest.TestCase):
    """唐奇安突破信号用前 20 根通道对比当前收盘,新高/新低可正常触发。"""

    def test_donchian_breakout_and_breakdown(self):
        base = [{"open": 100.0, "high": 102.0, "low": 98.0, "close": 100.0,
                 "volume": 1_000_000, "time": f"2026-06-{i + 1:02d}T05:00:00Z"}
                for i in range(29)]
        high_bars = base + [{"open": 101.0, "high": 108.0, "low": 100.5, "close": 106.0,
                             "volume": 1_200_000, "time": "2026-07-01T05:00:00Z"}]
        low_bars = base + [{"open": 99.0, "high": 99.5, "low": 93.0, "close": 94.0,
                            "volume": 1_200_000, "time": "2026-07-01T05:00:00Z"}]
        with patch.object(ci, "get_kline_adjusted", return_value=high_bars):
            res_hi = ci.compute_all("TEST.US", count=30)
        with patch.object(ci, "get_kline_adjusted", return_value=low_bars):
            res_lo = ci.compute_all("TEST.US", count=30)
        self.assertTrue(any("突破 20 日新高" in s for s in res_hi["signals"]))
        self.assertTrue(any("跌破 20 日新低" in s for s in res_lo["signals"]))


class TestGexUsesBsGammaFirst(unittest.TestCase):
    """calc_gex 优先用合约 IV 算 BS gamma,不被服务端 3 位小数 0.000 舍入成 0。"""

    def test_native_zero_overridden_by_bs_and_sources_counted(self):
        with patch.object(cgex, "get_underlying_price", return_value=350.0), \
             patch.object(cgex, "get_underlying_price_info", return_value={"session": "regular"}), \
             patch.object(cgex, "days_to_years", return_value=30 / 365.0), \
             patch.object(cgex, "get_option_chain", return_value=[
                 {"strike": 280.0, "call_iv": 0.45, "put_iv": 0.45},
                 {"strike": 350.0, "call_iv": 0.24, "put_iv": 0.25},
                 {"strike": 400.0, "call_iv": None, "put_iv": None},
             ]), \
             patch.object(cgex, "get_chain_oi", return_value={
                 "oi_mode": True,
                 "strikes": {
                     # 服务端 3 位小数把深度价外/价内腿舍入为 0.000,但合约 IV 有效
                     280.0: {"call_oi": 500, "put_oi": 1000,
                             "call_gamma": 0.0, "put_gamma": 0.0,
                             "call_iv": 0.45, "put_iv": 0.45},
                     # 合约缺 IV,回退到 chain IV
                     350.0: {"call_oi": 2000, "put_oi": 1500,
                             "call_gamma": 0.015, "put_gamma": 0.015,
                             "call_iv": None, "put_iv": None},
                     # 合约与 chain 都缺 IV,回退服务端 native gamma
                     400.0: {"call_oi": 300, "put_oi": 0,
                             "call_gamma": 0.003, "put_gamma": None,
                             "call_iv": None, "put_iv": None},
                 },
             }):
            res, txt = _capture(cgex.calc_gex, "AAPL.US", "2026-12-24", output_json=False)

        row_280 = next(r for r in res["per_strike"] if r["strike"] == 280.0)
        self.assertGreater(row_280["call_gamma"], 0.0)
        self.assertGreater(row_280["put_gamma"], 0.0)
        self.assertEqual(res["gamma_sources"], {
            "bs_contract_iv": 2,
            "bs_chain_iv": 2,
            "native": 1,
            "none": 1,
        })
        self.assertIn("BS gamma(合约IV)", txt)


class TestPortfolioGreeksDeadTheta(unittest.TestCase):
    """组合 Greeks 必须传导 theta_source,dead_zero/None 不得当成有利时间衰减。"""

    def test_short_ten_puts_with_dead_zero_theta_becomes_none(self):
        with patch.object(cog, "get_quote", return_value={
            "greeks": {"delta": -0.05, "gamma": 0.004, "theta": -0.001,
                       "vega": 0.03, "rho": -0.01},
            "greeks_source": "native",
            "theta_source": "dead_zero",
            "iv_pct": 28.0,
        }):
            legs = [{"underlying": "AAPL.US", "expiry": "2026-12-04",
                     "strike": 300.0, "type": "PUT", "action": "SELL", "quantity": 10}]
            res = cog.calc_portfolio_greeks(legs)

        self.assertIsNone(res["portfolio_greeks"]["theta"])
        self.assertFalse(res["theta_valid"])
        self.assertEqual(len(res["theta_invalid_legs"]), 1)
        self.assertIsNone(res["detail"][0]["theta"])
        self.assertEqual(res["detail"][0]["theta_source"], "dead_zero")
        self.assertNotIn("有利", res["interpretation"])
        self.assertIn("theta 无有效数据", res["interpretation"])

    def test_backfill_count_propagates_when_all_valid(self):
        with patch.object(cog, "get_quote", return_value={
            "greeks": {"delta": -0.4, "gamma": 0.01, "theta": -0.15,
                       "vega": 0.12, "rho": -0.04},
            "greeks_source": "native",
            "theta_source": "bs_backfill",
            "iv_pct": 30.0,
        }):
            legs = [{"underlying": "AAPL.US", "expiry": "2026-12-18",
                     "strike": 340.0, "type": "PUT", "action": "SELL", "quantity": 2}]
            res = cog.calc_portfolio_greeks(legs)

        self.assertTrue(res["theta_valid"])
        self.assertEqual(res["theta_backfilled_legs"], 1)
        self.assertAlmostEqual(res["portfolio_greeks"]["theta"], 30.0, places=4)


class TestAhPremiumHongKongDate(unittest.TestCase):
    """A/H 溢价时间戳按港股当地时区格式化,不再因 UTC 提前一天出现周日。"""

    def test_live_timestamps_map_to_mon_tue_wed_hkt(self):
        # 实盘样本:1795363200 = UTC 2026-11-22 16:00(周日) = HKT 2026-11-23 00:00(周一)
        klines = [
            {"timestamp": "1795363200", "aprice": "12.390", "hprice": "10.310",
             "currency_rate": "0.8500", "ahpremium_rate": "-0.292696"},
            {"timestamp": "1795449600", "aprice": "12.430", "hprice": "10.250",
             "currency_rate": "0.8519", "ahpremium_rate": "-0.297508"},
            {"timestamp": "1795536000", "aprice": "12.590", "hprice": "10.210",
             "currency_rate": "0.8498", "ahpremium_rate": "-0.310845"},
        ]
        with patch.object(ahp, "get_ah_premium", return_value=klines):
            res, txt = _capture(ahp.fetch_ah_premium, "939.HK", output_json=False)
        self.assertEqual([k["date"] for k in res["klines"]],
                         ["2026-11-23", "2026-11-24", "2026-11-25"])
        self.assertNotIn("2026-11-22", txt)
        self.assertIn("2026-11-25", txt)

        # 分时模式按港股当地时分显示
        self.assertEqual(ahp._ts_label("1795570200", intraday=True), "11-25 09:30")


class TestValuationFullIndustryRank(unittest.TestCase):
    """估值同行排名用 industry-valuation dist 全行业排名,不拿 5 条预览报 1/5。"""

    def _mock_valuation(self):
        return {
            "history": {"metrics": {"pe": {
                "circle": "38.93", "median": "29.0",
                "list": [{"value": str(25 + i)} for i in range(10)],
            }}},
            "peers": {"pe": {
                "industry_median": "0.74",
                "list": [
                    {"counter_id": "ST/US/AAPL", "name": "Apple", "value": "38.9288"},
                    {"counter_id": "ST/US/STX", "name": "Seagate", "value": "24.8752"},
                    {"counter_id": "ST/US/DELL", "name": "Dell", "value": "16.5005"},
                    {"counter_id": "ST/US/WDC", "name": "WD", "value": "10.3446"},
                    {"counter_id": "ST/US/SNDK", "name": "Sandisk", "value": "4.5686"},
                ],
            }},
        }

    def test_uses_dist_rank_and_median(self):
        dist = {"pe": {"low": "0.736", "high": "38.929", "median": "24.385",
                       "value": "38.929", "ranking": "1",
                       "rank_index": "19", "rank_total": "19"}}
        with patch.object(gvp, "get_valuation", return_value=self._mock_valuation()), \
             patch.object(gvp, "get_industry_valuation_dist", return_value=dist):
            res, txt = _capture(gvp.analyze, "AAPL.US", output_json=False)

        peers = res["peers"]
        self.assertEqual(peers["target_rank"], 19)
        self.assertEqual(peers["total_peers"], 19)
        self.assertEqual(peers["preview_count"], 5)
        self.assertAlmostEqual(peers["industry_median"], 24.385, places=3)
        self.assertAlmostEqual(peers["preview_industry_median_raw"], 0.74, places=2)
        self.assertEqual(peers["rank_basis"], "industry-valuation dist(全行业)")
        self.assertIn("19/19", txt)
        self.assertNotIn("1/5", txt)

    def test_dist_unavailable_leaves_rank_none(self):
        with patch.object(gvp, "get_valuation", return_value=self._mock_valuation()), \
             patch.object(gvp, "get_industry_valuation_dist", side_effect=RuntimeError("no dist")):
            res, txt = _capture(gvp.analyze, "AAPL.US", output_json=False)

        self.assertIsNone(res["peers"]["target_rank"])
        self.assertIsNone(res["peers"]["total_peers"])
        self.assertEqual(res["peers"]["rank_basis"], "unavailable")
        self.assertIn("完整行业排名不可得", txt)
        self.assertNotIn("1/5", txt)


class TestOiAndWallPositionLabels(unittest.TestCase):
    """Put 墙在现价上方(或 Call 墙在现价下方)时不误标下方支撑/上方阻力。"""

    def test_get_option_oi_all_puts_above_spot(self):
        oi_data = {
            "oi_mode": True,
            "strikes": {
                105.0: {"call_oi": 100, "put_oi": 5000, "call_delta": 0.3, "put_delta": -0.7},
                110.0: {"call_oi": 200, "put_oi": 2000, "call_delta": 0.2, "put_delta": -0.8},
            },
            "total_call_oi": 300,
            "total_put_oi": 7000,
            "pc_oi_ratio": 23.333,
            "strikes_queried": 2,
        }
        with patch.object(goi, "get_underlying_price", return_value=100.0), \
             patch.object(goi, "get_underlying_price_info", return_value={}), \
             patch.object(goi, "get_chain_oi", return_value=oi_data):
            res, txt = _capture(goi.analyze, "TEST.US", date="2026-12-18", output_json=False)
        self.assertIn("非下方支撑", res["put_oi_wall"]["position"])
        self.assertNotIn(",下方支撑", txt)

    def test_get_put_call_wall_fallback_does_not_label_above_put_as_support(self):
        chain = [{"strike": 110.0, "put_vol": 500, "call_vol": 400, "put_iv": 0.3, "call_iv": 0.3}]
        oi_data = {"oi_mode": False}
        with patch.object(gpcw, "get_underlying_price", return_value=100.0), \
             patch.object(gpcw, "get_underlying_price_info", return_value={}), \
             patch.object(gpcw, "get_option_chain", return_value=chain), \
             patch.object(gpcw, "get_chain_oi", return_value=oi_data):
            _res, txt = _capture(gpcw.analyze_walls, "TEST.US", date="2026-12-18", output_json=False)
        self.assertIn("现价下方无 Put 持仓", txt)
        self.assertNotIn("预计区间: 110.0(支撑)", txt)


class TestGammaProfileAdaptiveDedup(unittest.TestCase):
    """Gamma 剖面 S/R 去重用行权价间距中位数 h,而非硬编码 2.0。"""

    def test_half_dollar_strikes_keep_peaks_1_5_apart(self):
        # 间距 0.5 的链:在 98.0 与 99.5 两处放明显 Put OI 峰(相距 1.5 < 2.0,但 > h=0.5)
        oi_by_k = {
            97.0: 100, 97.5: 200, 98.0: 5000, 98.5: 100,
            99.0: 100, 99.5: 4500, 100.0: 100, 100.5: 100,
        }
        legs = [{"strike": k, "iv": 0.25, "oi": float(oi), "T": 0.1, "side": "P"}
                for k, oi in oi_by_k.items()]
        legs.append({"strike": 102.0, "iv": 0.25, "oi": 1000.0, "T": 0.1, "side": "C"})
        sr = cgp._sr_levels(legs, spot=101.0, top_n=3)
        prices = [p["price"] for p in sr["support"]]
        self.assertEqual(len(prices), 2)
        self.assertTrue(any(abs(p - 99.5) < 0.15 for p in prices))
        self.assertTrue(any(abs(p - 98.0) < 0.15 for p in prices))


class TestUsEarlyCloseT(unittest.TestCase):
    """美股规则半日市(13:00 ET 收盘)的 T 与未收盘判定。"""

    def test_rule_dates(self):
        self.assertTrue(common.us_early_close(date(2026, 11, 27)))   # 感恩节翌日
        self.assertTrue(common.us_early_close(date(2026, 12, 24)))   # 周四平安夜
        self.assertFalse(common.us_early_close(date(2026, 7, 3)))    # 周五独立日调休(休市,非半日)
        self.assertTrue(common.us_early_close(date(2025, 7, 3)))     # 周四独立日前夕
        self.assertFalse(common.us_early_close(date(2026, 11, 30)))  # 普通周一

    def test_days_to_years_half_day_close_at_1300_et(self):
        t_half = common.days_to_years("2026-11-27", now=datetime(2026, 11, 27, 12, 30))
        t_full = common.days_to_years("2026-11-30", now=datetime(2026, 11, 30, 12, 30))
        self.assertAlmostEqual(t_half * 365 * 24, 0.5, places=6)
        self.assertAlmostEqual(t_full * 365 * 24, 3.5, places=6)

    def test_is_bar_in_progress_uses_1300_on_half_day(self):
        self.assertTrue(common.is_bar_in_progress("2026-11-27", "AAPL.US", now=datetime(2026, 11, 27, 12, 30)))
        self.assertFalse(common.is_bar_in_progress("2026-11-27", "AAPL.US", now=datetime(2026, 11, 27, 13, 30)))


class TestUnifiedMarketTempThresholds(unittest.TestCase):
    """get_market_temp 与 daily_briefing 使用同一套 70/50/30 档位。"""

    def test_both_scripts_match_across_boundaries(self):
        for val in (None, 0, 29.9, 30, 49.9, 50, 69.9, 70, 100):
            with self.subTest(val=val):
                self.assertEqual(gmt._temp_emoji(val), dbf._temp_emoji(val))
                self.assertEqual(gmt._temp_emoji(val), common.market_temp_label(val))


class TestTopMoversPctFormatting(unittest.TestCase):
    """异动榜涨跌幅从小数转为百分比,港股不加美元符号。"""

    def test_fractional_change_formatted_as_percent(self):
        data = {
            "updated_at": "2026-11-25 10:00",
            "events": [
                {"stock": {"symbol": "CRCL.US", "name": "Circle", "last_done": "47.720", "change": "-0.0831"},
                 "alert_reason": "波动超 20 日均值", "post": {}},
                {"stock": {"symbol": "0700.HK", "name": "腾讯控股", "last_done": "400.00", "change": "0.025"},
                 "alert_reason": "放量上涨", "post": {}},
            ],
        }
        with patch.object(gtm, "get_top_movers", return_value=data):
            res, txt = _capture(gtm.fetch_top_movers, market=None, output_json=False)
        self.assertAlmostEqual(res["events"][0]["change_pct"], -8.31, places=2)
        self.assertAlmostEqual(res["events"][1]["change_pct"], 2.5, places=2)
        self.assertIn("$47.720 (-8.31%)", txt)
        self.assertIn("0700.HK 腾讯控股 400.00 (+2.50%)", txt)
        self.assertNotIn("$400.00", txt)


if __name__ == "__main__":
    unittest.main()
