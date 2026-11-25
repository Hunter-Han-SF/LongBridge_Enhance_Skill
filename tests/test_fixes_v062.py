"""v0.6.2 修复回归:2026-11-24 第六轮审计的高优先级 5 项。

夹具均取自 2026-11-24 的实盘数据(CLI 0.27.1):
  1. chain 同行权价重复行:TSLA 2026-11-27 有 20 个行权价各返回两行
     (一行真实、一行全零或带陈旧垃圾值),且先后顺序每次调用都会变。
     修复:common.get_option_chain 入口统一合并,每个行权价只返回一行。
  2. 入场规则的支撑/阻力聚类:高点低点混在一起且逐点链式合并,
     TSLA 337~459 的 43 个枢轴点曾被并成一个"价位"。
     修复:高低点分开聚类、簇宽不超过容差,价位按区间(下沿/上沿)使用。
  3. 财务健康科目名带币种后缀("营业收入(USD)"),裸名映射表匹配不上。
     修复:先按 ranking_code,再按去掉币种后缀的名称匹配。
  4. IV/HV 期限错配:最近到期日的 IV(可能只剩 1 天)被拿去比 30 日 HV。
     修复:IV 取期限最接近 HV 窗口的到期日,期限相差过大时给出提示。
  5. 分析师共识:forecast-eps 是按日期升序的共识快照,取首条拿到 2018 年的旧值;
     目标价"中值"用 (最高+最低)/2 而非服务端共识目标价。
     修复:取日期最新的快照;目标价优先用 instratings.target。

运行: python -m unittest tests.test_fixes_v062 -v
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest

_HERE = os.path.dirname(__file__)
_SCRIPTS = os.path.normpath(os.path.join(_HERE, "..", "scripts"))
for _sub in ("", "decision", "fundamental", "quote", "technical"):
    sys.path.insert(0, os.path.join(_SCRIPTS, _sub))

import common  # noqa: E402
import analyze_buy_sell  # noqa: E402
import calc_exercise_prob  # noqa: E402
import check_entry_rules as entry  # noqa: E402
import get_analyst_consensus  # noqa: E402
import get_financial_health as health  # noqa: E402
import get_iv_history  # noqa: E402
import get_iv_term_structure  # noqa: E402
import get_option_quote  # noqa: E402
import get_option_volatility  # noqa: E402


def _run(func, *args, **kwargs):
    """调用会打印的入口并吞掉 stdout,返回结果。"""
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


# --------------------------------------------------------------------------- #
# 1. chain 重复行权价
# --------------------------------------------------------------------------- #

# TSLA 2026-11-27 实盘链的裁剪版(2026-11-24 09:2x ET 抓取,正股 385.46)。
# 真实行取自实测;垃圾行两种形态:全零,或带陈旧的非零值(385P 0.42/0.043、
# 400C 0.23/0.136——只拦 ==0 的防护会放过这一种)。
_TSLA_REAL = {
    375.0: ("14.75", "0.505", "4.50", "0.535"),
    380.0: ("12.03", "0.535", "6.05", "0.517"),
    385.0: ("8.75", "0.502", "8.20", "0.511"),
    390.0: ("6.28", "0.490", "10.65", "0.494"),
    395.0: ("4.25", "0.476", "13.40", "0.466"),
    400.0: ("2.75", "0.465", "17.13", "0.472"),
    405.0: ("1.85", "0.471", "19.21", "0.404"),
    410.0: ("1.03", "0.455", "24.55", "0.331"),
}
_TSLA_JUNK = {
    385.0: ("0", "0.000", "0.42", "0.043"),
    400.0: ("0.23", "0.136", "0", "0.000"),
}
TSLA_SPOT = 385.46
# 实测同一张链连续三次抓取得到的三种行序(哪一边在前每次都不同)
TSLA_ORDERS = ({380.0, 385.0, 400.0}, {380.0}, {385.0, 400.0}, set())


def _row(strike, call_last, call_iv, put_last, put_iv):
    return {"strike": str(strike), "call_last": call_last, "call_iv": call_iv,
            "call_vol": "0", "put_last": put_last, "put_iv": put_iv, "put_vol": "0",
            "standard": "true"}


def tsla_chain(junk_first) -> list[dict]:
    """实盘形态的链。junk_first 给出"垃圾行在前"的行权价集合,其余真实行在前。"""
    rows = []
    for strike in sorted(_TSLA_REAL):
        real = _row(strike, *_TSLA_REAL[strike])
        junk = _row(strike, *_TSLA_JUNK.get(strike, ("0", "0.000", "0", "0.000")))
        rows += [junk, real] if strike in junk_first else [real, junk]
    return rows


class TestChainDuplicateRows(unittest.TestCase):
    """同一行权价的多行必须合并成一行,且结果不依赖返回顺序。"""

    def test_merged_chain_is_order_independent(self):
        merged = [common._merge_chain_duplicates(tsla_chain(order)) for order in TSLA_ORDERS]
        for rows in merged:
            self.assertEqual(len(rows), len(_TSLA_REAL))
            self.assertEqual({float(r["strike"]) for r in rows}, set(_TSLA_REAL))
        for other in merged[1:]:
            self.assertEqual(merged[0], other)

    def test_real_values_survive(self):
        rows = {float(r["strike"]): r
                for r in common._merge_chain_duplicates(tsla_chain({380.0, 385.0, 400.0}))}
        for strike, (call_last, call_iv, put_last, put_iv) in _TSLA_REAL.items():
            self.assertEqual(rows[strike]["call_iv"], float(call_iv), f"{strike} call IV")
            self.assertEqual(rows[strike]["call_last"], float(call_last), f"{strike} call last")
            self.assertEqual(rows[strike]["put_iv"], float(put_iv), f"{strike} put IV")
            self.assertEqual(rows[strike]["put_last"], float(put_last), f"{strike} put last")
        self.assertNotIn(0.136, [r["call_iv"] for r in rows.values()])
        self.assertNotIn(0.043, [r["put_iv"] for r in rows.values()])

    def test_clean_chain_is_returned_untouched(self):
        clean = [_row(k, *_TSLA_REAL[k]) for k in sorted(_TSLA_REAL)]
        self.assertIs(common._merge_chain_duplicates(clean), clean)

    def test_get_option_chain_merges_cli_output(self):
        orig = common.run_cli
        common.run_cli = lambda *a, **k: tsla_chain({385.0, 400.0})
        try:
            rows = common.get_option_chain("TSLA.US", "2026-11-27")
        finally:
            common.run_cli = orig
        self.assertEqual(len(rows), len(_TSLA_REAL))
        self.assertEqual(common.get_atm_iv(rows, TSLA_SPOT, "PUT"), 0.511)
        self.assertEqual(common.get_atm_iv(rows, TSLA_SPOT, "CALL"), 0.502)

    def test_exercise_prob_no_longer_depends_on_row_order(self):
        """修复前:垃圾行在前时 400 Call 算成 0.22%(真实 19.64%),380 Put 直接报错。"""
        seen = set()
        for order in TSLA_ORDERS:
            orig = (calc_exercise_prob.get_underlying_price, calc_exercise_prob.get_option_chain,
                    calc_exercise_prob.days_to_years)
            calc_exercise_prob.get_underlying_price = lambda s: TSLA_SPOT
            calc_exercise_prob.get_option_chain = lambda u, e: common._merge_chain_duplicates(tsla_chain(order))
            calc_exercise_prob.days_to_years = lambda e: 3.27 / 365
            try:
                call = _run(calc_exercise_prob.exercise_prob, "TSLA.US", "2026-11-27", 400, "CALL",
                            output_json=True)
                put = _run(calc_exercise_prob.exercise_prob, "TSLA.US", "2026-11-27", 380, "PUT",
                           output_json=True)
            finally:
                (calc_exercise_prob.get_underlying_price, calc_exercise_prob.get_option_chain,
                 calc_exercise_prob.days_to_years) = orig
            seen.add((call["exercise_prob_bs"], put["exercise_prob_bs"]))
            self.assertEqual(call["iv_pct"], 46.5)
            self.assertAlmostEqual(call["exercise_prob_bs"], 19.64, delta=0.02)
            self.assertEqual(put["iv_pct"], 51.7)
            self.assertAlmostEqual(put["exercise_prob_bs"], 39.15, delta=0.02)
        self.assertEqual(len(seen), 1)

    def test_term_structure_is_stable(self):
        far = [_row(385.0, "30", "0.45", "30", "0.45")]
        results = []
        for order in TSLA_ORDERS:
            orig = (get_iv_term_structure.get_underlying_price, get_iv_term_structure.get_option_expirations,
                    get_iv_term_structure.get_option_chain, get_iv_term_structure.days_to_years)
            get_iv_term_structure.get_underlying_price = lambda s: TSLA_SPOT
            get_iv_term_structure.get_option_expirations = lambda s: ["2026-11-27", "2027-01-15"]
            get_iv_term_structure.get_option_chain = lambda u, e: (
                common._merge_chain_duplicates(tsla_chain(order)) if e == "2026-11-27" else far)
            get_iv_term_structure.days_to_years = lambda e: 3.27 / 365
            try:
                results.append(_run(get_iv_term_structure.analyze, "TSLA.US", count=2, output_json=True)
                               ["term_structure"][0])
            finally:
                (get_iv_term_structure.get_underlying_price, get_iv_term_structure.get_option_expirations,
                 get_iv_term_structure.get_option_chain, get_iv_term_structure.days_to_years) = orig
        for row in results:
            self.assertEqual(row["atm_strike"], 385.0)
            self.assertEqual(row["call_iv_pct"], 50.2)
            self.assertEqual(row["put_iv_pct"], 51.1)
        self.assertEqual(results[0], results[1])

    def test_constant_tenor_iv_sampling_is_stable(self):
        """恒定 30 日 ATM IV(IV Rank 的数据源)曾因行序不同得到 43.88% / 45.30%。"""
        tenors = {"2026-11-27": 3.27, "2027-01-15": 52.2}
        far = [_row(385.0, "30", "0.45", "30", "0.45")]
        results = []
        for order in TSLA_ORDERS:
            orig = (get_iv_history.get_underlying_price, get_iv_history.get_option_expirations,
                    get_iv_history.get_option_chain, get_iv_history.days_to_years)
            get_iv_history.get_underlying_price = lambda s: TSLA_SPOT
            get_iv_history.get_option_expirations = lambda s: list(tenors)
            get_iv_history.get_option_chain = lambda u, e: (
                common._merge_chain_duplicates(tsla_chain(order)) if e == "2026-11-27" else far)
            get_iv_history.days_to_years = lambda e: tenors[e] / 365
            try:
                results.append(get_iv_history.get_current_atm_iv("TSLA.US"))
            finally:
                (get_iv_history.get_underlying_price, get_iv_history.get_option_expirations,
                 get_iv_history.get_option_chain, get_iv_history.days_to_years) = orig
        for iv, meta in results:
            self.assertAlmostEqual(meta["source_expiries"][0]["iv"], 0.5065)  # (0.502+0.511)/2
            self.assertAlmostEqual(iv, results[0][0])
        self.assertAlmostEqual(results[0][0], 0.4529, delta=0.0005)

    def test_option_quote_ignores_junk_nonzero_iv(self):
        """v0.6.1 的防护只拦零 IV;垃圾行带非零 IV(0.136)时仍会被采用。"""
        orig = (get_option_quote.run_cli, get_option_quote.get_underlying_price,
                get_option_quote.get_option_contract_metrics, common.run_cli)
        get_option_quote.run_cli = lambda *a, **k: None
        get_option_quote.get_underlying_price = lambda s: TSLA_SPOT
        get_option_quote.get_option_contract_metrics = lambda syms: {}
        common.run_cli = lambda *a, **k: tsla_chain({385.0, 400.0})
        try:
            for _ in range(2):
                r = get_option_quote.get_quote("TSLA.US", "2026-11-27", 400, "CALL", quiet=True)
                self.assertEqual(r["iv_pct"], 46.5)
                self.assertEqual(r["last"], 2.75)
        finally:
            (get_option_quote.run_cli, get_option_quote.get_underlying_price,
             get_option_quote.get_option_contract_metrics, common.run_cli) = orig


# --------------------------------------------------------------------------- #
# 2. 支撑/阻力聚类
# --------------------------------------------------------------------------- #

def _pivots(kind, prices, start=20):
    return [{"idx": start + i * 5, "price": p, "kind": kind} for i, p in enumerate(prices)]


def _assert_clusters_are_sound(test, pivots, levels):
    """每个价位只由同一种枢轴点组成,touches 等于落在区间内的该类点数。"""
    for x in levels:
        members = [p for p in pivots if p["kind"] == x["kind"]
                   and x["low"] - 1e-9 <= p["price"] <= x["high"] + 1e-9]
        test.assertEqual(len(members), x["touches"])
        test.assertAlmostEqual(x["price"], sum(p["price"] for p in members) / len(members))


class TestClusterLevels(unittest.TestCase):
    """高低点分开聚类、簇宽不超过容差;价位是区间。"""

    def test_highs_and_lows_are_clustered_separately(self):
        # 价格 100、ATR 10 → 容差 8。低点 95/105 与高点 100 交错:混在一起且链式
        # 比较时会并成一个 touches=3 的"强"价位(均值 100)。
        pivots = _pivots("low", [95.0, 105.0]) + _pivots("high", [100.0], start=30)
        levels = entry.cluster_levels(pivots, 100.0, 10.0)
        self.assertEqual(len(levels), 3)
        self.assertEqual({x["kind"] for x in levels}, {"low", "high"})
        for x in levels:
            self.assertEqual(x["touches"], 1)
            self.assertEqual(x["low"], x["high"])  # 单点簇
        _assert_clusters_are_sound(self, pivots, levels)

    def test_no_chain_merging_within_a_kind(self):
        # 低点 100/105/110/115/120,容差 8:逐点链式比较会并成一个跨 20% 的簇
        pivots = _pivots("low", [100.0, 105.0, 110.0, 115.0, 120.0])
        levels = entry.cluster_levels(pivots, 100.0, 10.0)
        self.assertEqual([(x["low"], x["high"], x["touches"]) for x in levels],
                         [(100.0, 105.0, 2), (110.0, 115.0, 2), (120.0, 120.0, 1)])
        _assert_clusters_are_sound(self, pivots, levels)

    def test_tsla_live_pivots_keep_the_338_354_support(self):
        """实盘复盘(2026-11-24,TSLA 现价 387.34、ATR 18.65 → 容差 14.92):
        这 11 个近期枢轴点曾被并进 337~459 的 43 点巨型簇,均值 395.97。"""
        pivots = (_pivots("low", [338.15, 342.5, 345.88, 349.33, 354.1], start=150)
                  + _pivots("high", [366.5, 384.0, 386.8, 388.6, 404.4, 414.2], start=152))
        levels = entry.cluster_levels(pivots, 387.34, 18.65)
        self.assertGreaterEqual(len(levels), 5)
        self.assertLessEqual(max(x["touches"] for x in levels), 4)
        # 被测试过 3 次以上的 338~354 支撑必须还在,而不是整段消失
        support = [x for x in levels if x["kind"] == "low" and x["touches"] >= 3]
        self.assertEqual([(x["low"], x["high"], x["touches"]) for x in support],
                         [(338.15, 349.33, 4)])
        resistance = [x for x in levels if x["kind"] == "high" and x["touches"] >= 3]
        self.assertEqual([(x["low"], x["high"], x["touches"]) for x in resistance],
                         [(384.0, 388.6, 3)])
        for x in levels:
            self.assertLessEqual(x["high"] - x["low"], 14.92 + 1e-9)
        _assert_clusters_are_sound(self, pivots, levels)

    def test_zone_helpers_accept_point_levels(self):
        """旧式价位(只有 price)视为一个点:下沿 = 上沿 = price。"""
        point = {"price": 100, "touches": 2, "last_idx": 10}
        self.assertEqual(entry._zone_low(point), 100)
        self.assertEqual(entry._zone_high(point), 100)
        self.assertEqual(entry._zone_text(point), "100.00")
        zone = {"price": 344.0, "low": 338.15, "high": 349.33, "touches": 4, "last_idx": 5, "kind": "low"}
        self.assertEqual(entry._zone_text(zone), "338.15~349.33")


def _bars_from_closes(closes, volume=1_000_000):
    """按收盘价路径生成 K 线(高低点 = 收盘价上下 0.3),量恒定。"""
    return [{"open": c, "close": c, "high": c + 0.3, "low": c - 0.3, "volume": volume}
            for c in closes]


SUPPORT_LOWS = [96.0, 96.3, 95.8, 96.2, 96.5]


def _range_bars(tail):
    """在 96 附近的低点区与 104 的高点之间来回 5 轮(30 根),再接 tail。"""
    path, current = [], 104.0
    for low in SUPPORT_LOWS:
        path += [current + (low - current) * i / 3 for i in (1, 2, 3)]
        path += [low + (104.0 - low) * i / 3 for i in (1, 2, 3)]
        current = 104.0
    return _bars_from_closes(path + tail)


class TestZoneBasedStopAndTarget(unittest.TestCase):
    """止损量到支撑簇下沿、目标量到压力簇下沿;跌破以簇的下沿为准。"""

    def test_stop_is_support_zone_low_and_target_is_resistance_zone_low(self):
        f = entry.build_features(_range_bars([101.33, 98.67, 96.4, 98.0, 99.0, 98.0]), "TEST.US")
        self.assertEqual(f["last"], 98.0)
        # 枢轴点取 K 线的最高/最低价(收盘价上下 0.3);首根低点左侧不足 3 根,不算枢轴点
        zones = {(x["kind"], x["low"], x["high"]): x["touches"] for x in f["levels"]}
        self.assertEqual(zones, {("low", 95.5, 96.2): 5, ("high", 104.3, 104.3): 5})
        self.assertEqual(f["stop"], 95.5)      # 不是簇均值 95.94
        self.assertEqual(f["target"], 104.3)
        r = _run(entry.check_rules, f)
        self.assertEqual(r["rules"]["D5"]["status"], "clear")
        self.assertEqual(r["rules"]["B0"]["status"], "pass")
        self.assertIn("目标 104.30 / 入场 98.00 / 止损 95.50 → 盈亏比 2.52:1", r["rules"]["B0"]["evidence"])

    def test_price_inside_support_zone_still_counts_as_support(self):
        """回踩进支撑簇内(96.1 落在 95.5~96.2):止损放在簇下沿之下。"""
        f = entry.build_features(_range_bars([101.33, 98.67, 97.5, 99.0, 98.0, 96.1]), "TEST.US")
        self.assertEqual(f["last"], 96.1)
        self.assertEqual(f["support"]["kind"], "low")
        self.assertEqual((f["stop"], f["target"]), (95.5, 104.3))
        self.assertEqual(f["resistance"]["kind"], "high")

    def test_breakdown_requires_closing_below_zone_low(self):
        # 收在支撑簇内(96.1 > 95.5):不算跌破,依据里不得出现"结构颈线/强支撑"
        inside = _run(entry.check_rules, entry.build_features(
            _range_bars([101.33, 98.67, 97.5, 99.0, 98.0, 96.1]), "TEST.US"))
        self.assertEqual(inside["rules"]["D2"]["status"], "clear")
        self.assertNotIn("结构颈线/强支撑", inside["rules"]["D3"]["evidence"])
        # 收在簇下沿之下(95.0 < 95.5):刚跌破强支撑,被跌破的簇就在现价上方
        below = _run(entry.check_rules, entry.build_features(
            _range_bars([101.33, 98.67, 97.5, 99.0, 98.0, 95.0]), "TEST.US"))
        self.assertEqual(below["rules"]["D2"]["status"], "triggered")
        self.assertIn("跌破强支撑 95.50~96.20(触及4次)", below["rules"]["D2"]["evidence"])
        self.assertIn("上方压力 95.50~96.20", below["rules"]["D2"]["evidence"])
        self.assertEqual(below["rules"]["D3"]["status"], "triggered")
        self.assertIn("结构颈线/强支撑 95.50~96.20", below["rules"]["D3"]["evidence"])
        self.assertEqual(below["verdict"], "❌ 不买")


# --------------------------------------------------------------------------- #
# 3. 财务健康:科目名带币种后缀
# --------------------------------------------------------------------------- #

def _account(name, value, yoy="", code="", period="Q4 2026"):
    return {"name": name, "ranking_code": code,
            "values": [{"period": period, "year": 2026, "value": value, "yoy": yoy}]}


# AAPL 2026-11-24 实盘 financial-report 的科目名与数值(美股带 (USD),港股带 (HKD))
_AAPL_REPORT = {"list": {
    "IS": {"indicators": [{"accounts": [_account("每股收益(USD)", "2.0988", "14.08")]},
                          {"accounts": [_account("ROE", "111.8728", "", "roe")]},
                          {"accounts": [_account("营业收入(USD)", "114477000000.0000", "11.72", "operating_revenue")]},
                          {"accounts": [_account("净利润(USD)", "30711000000.0000", "11.81", "net_profit")]},
                          {"accounts": [_account("毛利率", "47.8873")]},
                          {"accounts": [_account("净利率", "26.8272", "", "net_profit_margin")]}]},
    "BS": {"indicators": [{"accounts": [_account("总资产(USD)", "404548000000.0000", "", "total_assets"),
                                        _account("总负债(USD)", "292455000000.0000")]},
                          {"accounts": [_account("权益乘数", "3.6090", "", "leverage")]},
                          {"accounts": [_account("净债务(USD)", "-42456000000.0000", "-111.8")]}]},
    "CF": {"indicators": [{"accounts": [_account("经营现金流(USD)", "28101000000.0000", "-5.47")]},
                          {"accounts": [_account("自由现金流(USD)", "16463375000.0000", "-11.14")]},
                          {"accounts": [_account("资本支出(USD)", "-2242000000.0000", "30.85")]}]},
}}


class TestFinancialHealthAccountNames(unittest.TestCase):
    """科目名带币种后缀时仍要匹配到标准键。"""

    def test_account_key_strips_currency_suffix(self):
        cases = [
            (_account("营业收入(USD)", "1", code="operating_revenue"), "revenue", "营业收入"),
            (_account("总负债(HKD)", "1"), "total_liabilities", "总负债"),
            (_account("净债务（CNY）", "1"), "net_debt", "净债务"),  # 全角括号
            (_account("经营现金流(USD)", "1"), "operating_cf", "经营现金流"),
            (_account("自由现金流(USD)", "1"), "fcf", "自由现金流"),
            (_account("资本支出(USD)", "1"), "capex", "资本支出"),
            (_account("每股收益(USD)", "1"), "eps", "每股收益"),
            (_account("净利润", "1"), "net_profit", "净利润"),  # 旧夹具的裸名仍可用
        ]
        for acc, key, name in cases:
            self.assertEqual(health._account_key(acc), (key, name), acc["name"])

    def test_unrelated_names_do_not_match(self):
        for name in ("现金及短期投资(USD)及占比", "经营现金流/(资本支出+分红+偿债）",
                     "举债总额(USD)", "存货(HKD)及占比"):
            self.assertIsNone(health._account_key(_account(name, "1"))[0], name)

    def test_suffixed_report_recovers_all_metrics(self):
        """修复前只剩毛利率/净利率/ROE 三项,结论恒为「关键指标不足」。"""
        orig = health.get_financial_report
        health.get_financial_report = lambda symbol: _AAPL_REPORT
        try:
            r = _run(health.analyze, "AAPL.US", output_json=True)
        finally:
            health.get_financial_report = orig
        table = {row["指标"]: row for row in r["table"]}
        self.assertEqual(table["最新报告期"]["备注"], "Q4 2026")
        self.assertEqual(len(r["items"]), 13)
        self.assertAlmostEqual(r["computed"]["debt_ratio_pct"], 72.29, places=2)
        self.assertAlmostEqual(r["computed"]["earnings_quality_pct"], 53.61, places=2)
        self.assertAlmostEqual(table["营收 YoY"]["值"], 11.72, places=2)
        self.assertAlmostEqual(table["净利润 YoY"]["值"], 11.81, places=2)
        self.assertEqual(table["负债率"]["灯"], "🟡")
        self.assertEqual(table["经营现金流 YoY"]["灯"], "🟡")
        self.assertEqual(table["FCF/净利润"]["灯"], "🟡")
        self.assertLess(table["净债务"]["值"], 0)
        self.assertEqual((r["greens"], r["reds"], r["scored_metrics"]), (5, 0, 8))
        self.assertNotIn("关键指标不足", r["verdict"])


# --------------------------------------------------------------------------- #
# 4. IV/HV 期限对齐
# --------------------------------------------------------------------------- #

_DAYS = {"2026-11-25": 1.28, "2026-12-04": 10.28, "2026-12-18": 24.28,
         "2026-12-31": 37.2, "2027-01-15": 52.2}
_IV = {"2026-11-25": 0.328, "2026-12-04": 0.255, "2026-12-18": 0.257,
       "2026-12-31": 0.226, "2027-01-15": 0.245}


def _fake_days(expiry, today=None, *, now=None):
    """与真实 days_to_years 同约定: 无法解析的到期日抛 ValueError。"""
    assert today is None and now is None
    if expiry not in _DAYS:
        raise ValueError(f"time data {expiry!r} does not match format")
    return _DAYS[expiry] / 365


def _chain_for(expiry):
    return [{"strike": 350, "call_iv": _IV[expiry], "put_iv": _IV[expiry],
             "call_last": 6.0, "put_last": 6.4, "standard": "true"}]


def _closes(count):
    return [{"close": 100.0 if i % 2 == 0 else 101.0} for i in range(count)]


class TestIvHvTenorAlignment(unittest.TestCase):
    """IV 取期限最接近 HV 窗口的到期日,不再默认取最近到期日。"""

    def test_nearest_tenor_expiry(self):
        orig = common.days_to_years
        common.days_to_years = _fake_days
        try:
            expiries = list(_DAYS)
            # 30 个交易日收益 ≈ 43.5 个自然日
            self.assertEqual(common.nearest_tenor_expiry(expiries, 30 * 365 / 252), "2026-12-31")
            self.assertEqual(common.nearest_tenor_expiry(expiries, 5), "2026-11-25")   # 1.28 天比 10.28 天更近
            self.assertEqual(common.nearest_tenor_expiry(expiries, 12), "2026-12-04")
            self.assertEqual(common.nearest_tenor_expiry(expiries, 52.2), "2027-01-15")
            self.assertIsNone(common.nearest_tenor_expiry([], 30))
            self.assertEqual(common.nearest_tenor_expiry(["bad-date", "2027-01-15"], 50), "2027-01-15")
        finally:
            common.days_to_years = orig

    def _analyze(self, **kwargs):
        orig = (get_option_volatility.get_underlying_price, get_option_volatility.get_option_expirations,
                get_option_volatility.get_option_chain, get_option_volatility.get_kline_adjusted,
                get_option_volatility.days_to_years, common.days_to_years)
        get_option_volatility.get_underlying_price = lambda s: 349.08
        get_option_volatility.get_option_expirations = lambda s: list(_DAYS)
        get_option_volatility.get_option_chain = lambda u, e: _chain_for(e)
        get_option_volatility.get_kline_adjusted = lambda s, count: _closes(count)
        get_option_volatility.days_to_years = _fake_days
        common.days_to_years = _fake_days
        try:
            return _run(get_option_volatility.analyze, "AAPL.US", output_json=True, **kwargs)
        finally:
            (get_option_volatility.get_underlying_price, get_option_volatility.get_option_expirations,
             get_option_volatility.get_option_chain, get_option_volatility.get_kline_adjusted,
             get_option_volatility.days_to_years, common.days_to_years) = orig

    def test_default_picks_tenor_matched_expiry(self):
        r = self._analyze()
        self.assertEqual(r["expiry"], "2026-12-31")      # 不是最近的 2026-11-25
        self.assertAlmostEqual(r["iv_days"], 37.2)
        self.assertEqual(r["hv_days"], 26)               # 37.2 个自然日 ≈ 26 个交易日收益
        self.assertIsNone(r["tenor_warning"])
        self.assertAlmostEqual(r["iv_pct"], 22.6)

    def test_explicit_expiry_aligns_hv_window(self):
        r = self._analyze(expiry="2026-12-18")
        self.assertEqual(r["hv_days"], 17)               # 24.28 × 252/365
        self.assertIsNone(r["tenor_warning"])

    def test_mismatched_pair_is_flagged(self):
        """显式指定最近到期日又坚持 30 日 HV:照算,但必须提示期限不对齐。"""
        r = self._analyze(expiry="2026-11-25", hv_days=30)
        self.assertEqual(r["hv_days"], 30)
        self.assertIn("期限不对齐", r["tenor_warning"])
        self.assertIn("IV 剩余 1 个自然日", r["tenor_warning"])

    def test_too_small_hv_window_is_rejected(self):
        with self.assertRaises(ValueError):
            self._analyze(hv_days=1)

    def test_dashboard_options_dimension_uses_tenor_matched_expiry(self):
        """analyze_buy_sell 的期权维度同样不能拿最近到期日的 IV 比 30 日 HV。"""
        seen = []
        orig = (analyze_buy_sell.get_option_volume_realtime, analyze_buy_sell.get_option_expirations,
                analyze_buy_sell.get_option_chain, analyze_buy_sell.get_underlying_price,
                analyze_buy_sell.get_atm_iv, analyze_buy_sell.get_kline_adjusted, common.days_to_years)
        analyze_buy_sell.get_option_volume_realtime = lambda s: {}
        analyze_buy_sell.get_option_expirations = lambda s: list(_DAYS)
        analyze_buy_sell.get_option_chain = lambda u, e: seen.append(e) or _chain_for(e)
        analyze_buy_sell.get_underlying_price = lambda s: 349.08
        analyze_buy_sell.get_atm_iv = lambda chain, price, *a: chain[0]["call_iv"]
        analyze_buy_sell.get_kline_adjusted = lambda s, count: _closes(count)
        common.days_to_years = _fake_days
        try:
            score, detail = analyze_buy_sell._dim_options("AAPL.US", [], [])
        finally:
            (analyze_buy_sell.get_option_volume_realtime, analyze_buy_sell.get_option_expirations,
             analyze_buy_sell.get_option_chain, analyze_buy_sell.get_underlying_price,
             analyze_buy_sell.get_atm_iv, analyze_buy_sell.get_kline_adjusted, common.days_to_years) = orig
        self.assertEqual(seen, ["2026-12-31"])
        self.assertIn("IV/HV", detail)


# --------------------------------------------------------------------------- #
# 5. 分析师共识:最新快照 + 共识目标价
# --------------------------------------------------------------------------- #

# 实盘形态:forecast-eps 是按日期升序的共识快照序列(AAPL 共 343 条,首条 2018-10-31)
_SNAPSHOTS = [
    {"forecast_eps_mean": "5.368", "forecast_eps_highest": "5.368", "forecast_eps_lowest": "5.368",
     "forecast_eps_median": "5.368", "forecast_start_date": "1540425600",
     "forecast_end_date": "1540944000"},                                  # 2018-10-31
    {"forecast_eps_mean": "9.12", "forecast_eps_highest": "10.0", "forecast_eps_lowest": "8.2",
     "forecast_eps_median": "9.1", "forecast_start_date": "1795046400",
     "forecast_end_date": "1795132800"},                                  # 2026-11-20
    {"forecast_eps_mean": "9.419", "forecast_eps_highest": "10.06", "forecast_eps_lowest": "8.16",
     "forecast_eps_median": "9.4", "forecast_start_date": "1795305600",
     "forecast_end_date": "1795392000"},                                  # 2026-11-23
]
_EVALUATE = {"buy": 20, "over": 6, "hold": 13, "under": 3, "sell": 3, "total": 46, "no_opinion": 1}
_TARGET = {"highest_price": "425.000", "lowest_price": "250.000", "prev_close": "349.08"}


def _rating(with_instratings=True):
    rating = {"analyst": {"evaluate": dict(_EVALUATE), "target": dict(_TARGET),
                          "industry_name": "硬件、存储及外设", "industry_rank": 1, "industry_total": 31}}
    if with_instratings:
        rating["instratings"] = {"updated_at": "2026 年 11 月 23 日", "recommend": "buy",
                                 "target": "345.63128", "change": "-0.98794545662985"}
    return rating


class TestAnalystConsensus(unittest.TestCase):

    def _analyze(self, rating, snapshots):
        orig = (get_analyst_consensus.get_institution_rating, get_analyst_consensus.get_forecast_eps,
                get_analyst_consensus.get_underlying_price)
        get_analyst_consensus.get_institution_rating = lambda s: rating
        get_analyst_consensus.get_forecast_eps = lambda s: snapshots
        get_analyst_consensus.get_underlying_price = lambda s: 349.08
        try:
            return _run(get_analyst_consensus.analyze, "AAPL.US", output_json=True)
        finally:
            (get_analyst_consensus.get_institution_rating, get_analyst_consensus.get_forecast_eps,
             get_analyst_consensus.get_underlying_price) = orig

    def test_latest_snapshot_regardless_of_order(self):
        """修复前取首条 → 输出「至 2018-10-31 均值 5.368 分歧度 0%」。"""
        for snapshots in (_SNAPSHOTS, list(reversed(_SNAPSHOTS)), _SNAPSHOTS[1:] + _SNAPSHOTS[:1]):
            fc = self._analyze(_rating(), snapshots)["eps_forecast"]
            self.assertEqual(fc["as_of"], "2026-11-23")
            self.assertEqual(fc["period_end"], "2026-11-23")   # 历史键名,值是快照日期
            self.assertEqual(fc["mean"], 9.419)
            self.assertEqual((fc["lowest"], fc["highest"]), (8.16, 10.06))
            self.assertEqual(fc["dispersion_pct"], 20.2)

    def test_consensus_target_is_preferred_over_range_midpoint(self):
        """修复前 mid=(425+250)/2=337.5 → 距现价 -3.3%;共识目标价 345.63 为 -1.0%。"""
        r = self._analyze(_rating(), _SNAPSHOTS)["target_price"]
        self.assertEqual(r["consensus"], 345.63128)
        self.assertEqual(r["mid"], 345.63128)
        self.assertEqual(r["mid_source"], "consensus")
        self.assertEqual(r["range_midpoint"], 337.5)
        self.assertEqual(r["upside_to_mid_pct"], -1.0)
        self.assertEqual(r["upside_to_highest_pct"], 21.7)
        self.assertEqual(r["downside_to_lowest_pct"], -28.4)

    def test_range_midpoint_is_only_a_fallback(self):
        r = self._analyze(_rating(with_instratings=False), _SNAPSHOTS)["target_price"]
        self.assertIsNone(r["consensus"])
        self.assertEqual(r["mid"], 337.5)
        self.assertEqual(r["mid_source"], "range_midpoint")
        self.assertEqual(r["upside_to_mid_pct"], -3.3)

    def test_dashboard_uses_consensus_target(self):
        orig = analyze_buy_sell.analyst_analyze
        try:
            analyze_buy_sell.analyst_analyze = lambda symbol, quiet=True: self._analyze(_rating(), _SNAPSHOTS)
            bulls, bears = [], []
            score, detail = analyze_buy_sell._dim_analyst("AAPL.US", bulls, bears)
            self.assertIn("共识目标空间 -1.0%", detail)
            self.assertEqual((bulls, bears), ([], []))   # -1.0% 既够不上 +15% 也够不上 -10%

            # 共识目标价被现价明显超过时必须给出看空因素
            far = self._analyze(_rating(), _SNAPSHOTS)
            far["target_price"]["upside_to_mid_pct"] = -12.0
            analyze_buy_sell.analyst_analyze = lambda symbol, quiet=True: far
            bulls, bears = [], []
            penalized, _ = analyze_buy_sell._dim_analyst("AAPL.US", bulls, bears)
        finally:
            analyze_buy_sell.analyst_analyze = orig
        self.assertAlmostEqual(score - penalized, 10.0)
        self.assertEqual(len(bears), 1)
        self.assertIn("现价已高于共识目标 12.0%", bears[0])


if __name__ == "__main__":
    unittest.main()
