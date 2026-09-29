"""入场纪律检查器(28 条军规: 下跌12不买 + 上涨6不买 + 高胜率买点10)。

把一套纪律清单变成可执行的判定引擎: 对单一标的逐条检查,
输出「触发/未触发/需人工」三态,并给出最终入场结论。

规则分组(编号固定,输出与文档一致):
  下跌过程 12 不买  D1-D12   (D5 与 U4 同引擎: 止损可判定性/承受力)
  上涨过程 6 不买   U1-U6
  高胜率买点 10 条  B0-B9    (B0 = 盈亏比闸门,最低 1:1)

可自动判定 vs 需人工:
  自动 — 收盘新低/新高、缩量、RSI、斐波那契、趋势线/颈线、支撑压力距离、
         K 线形态(吞没/锤子/W底/旗形)、均线回踩、背离、财报距离、
         盘前 30 分钟(9:00-9:30,时区推算+休市日历)、热度榜命中、
         小市值(static 总股本×现价)、板块当日涨幅(industry-rank,
         需 --sector 指名或该股为领涨股——CLI 无个股→行业映射,实测)
  人工 — 刚止损不久(D8)、是否熟悉(D9)、昨日板块内跌幅排名(D6)、
         盘前盘后消息面异动(D11)
  人工项均可通过 CLI 参数回答(--recent-stopout yes 等),回答后转为自动判定。

⚠️ 形态识别为算法近似(pivot/聚类/回归),非精确图形匹配;结论是纪律参考,
非投资建议。支撑压力聚类与"强"的判定阈值见 _cluster_levels 注释。

用法:
    python check_entry_rules.py AAPL.US
    python check_entry_rules.py 0700.HK --max-stop-pct 6 --lookback 60 --json
    python check_entry_rules.py TSLA.US --recent-stopout yes --familiar no
    python check_entry_rules.py --demo        # 离线合成数据自检,无需登录
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.normpath(os.path.join(_HERE, "..")), _HERE,
           os.path.normpath(os.path.join(_HERE, "..", "technical"))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import (  # noqa: E402
    get_finance_calendar, get_heat_rank, get_heat_rank_keys, get_industry_rank,
    get_kline_adjusted, get_underlying_price, is_empty, normalize_records,
    print_error, print_json, run_cli, to_float,
)
from indicators import atr as _atr  # noqa: E402
from indicators import sma_series  # noqa: E402

PIVOT_K = 3          # pivot 确认窗口:左右各 3 根
NEAR_RES_PCT = 0.04  # D2「离强压力很近」: 上方压力距现价 ≤4%
BROKE_BARS = 3       # 「刚跌破/刚突破」= 最近 3 根内发生交叉
SHRINK_VOL = 0.8     # 缩量 = 成交量 < 0.8 × MA5量
EXPAND_VOL = 1.5     # 放量 = 成量 ≥ 1.5 × MA5量

# 规则名称(输出用,与用户纪律清单一一对应)
RULE_NAMES = {
    "D1": "收盘价创近期新低",
    "D2": "刚跌破强支撑且紧邻强压力",
    "D3": "刚跌破上行趋势线/斐波那契61.8%/结构颈线",
    "D4": "下跌途中缩量反弹",
    "D5": "止损无法确定或超出承受力",
    "D6": "昨日板块内跌幅居前(前10%)",
    "D7": "持续下跌+财报前跌幅异常放大",
    "D8": "刚刚止损不久",
    "D9": "不熟悉/累计跌幅过大",
    "D10": "大跌后社群热度飙升(小市值)",
    "D11": "盘前盘后非财报消息面异动",
    "D12": "盘前 30 分钟(9:00-9:30)不买",
    "U1": "缩量创新高",
    "U2": "创历史新高但远离支撑",
    "U3": "突破压力后紧邻下一强压力",
    "U4": "止损超出承受力(支撑太宽)",
    "U5": "日线严重超买 RSI(6)>90",
    "U6": "RSI(6)>80 且顶背离",
    "B0": "盈亏比闸门(最低 1:1)",
    "B1": "放量突破压力/前高后缩量回踩",
    "B2": "下降趋势线放量突破后回踩不破",
    "B3": "上升旗形整理后放量突破旗面",
    "B4": "W底/头肩底放量突破颈线后回踩不破",
    "B5": "连续上涨首次回踩 5/10 日线不破",
    "B6": "缩量阴线后放量看涨吞没",
    "B7": "缩量创新低后放量标准锤子线",
    "B8": "板块突破日成分股放量实体大阳突破",
    "B9": "回撤不破斐波那契+超卖+底背离+止跌",
}


# ---------------------------------------------------------------------------
# 基础序列工具(纯函数,便于离线测试)
# ---------------------------------------------------------------------------

def rolling_mean(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    for i in range(len(vals)):
        if i + 1 >= n:
            out[i] = sum(vals[i + 1 - n:i + 1]) / n
    return out


def rsi_series(closes: list[float], n: int = 14) -> list[float | None]:
    """Wilder RSI 序列(前 n 根为 None)。横盘无波动(gain=loss=0)返回中性 50,
    与 indicators.rsi 口径一致——否则停牌/横盘会被误判 RSI=100 严重超买。"""
    out: list[float | None] = [None] * len(closes)
    gain = loss = 0.0
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        g, d = max(ch, 0.0), max(-ch, 0.0)
        if i <= n:
            gain += g
            loss += d
            if i == n:
                gain, loss = gain / n, loss / n
                out[i] = (100.0 if gain > 0 else 50.0) if loss == 0 \
                    else 100 - 100 / (1 + gain / loss)
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + d) / n
            out[i] = (100.0 if gain > 0 else 50.0) if loss == 0 \
                else 100 - 100 / (1 + gain / loss)
    return out


def find_pivots(highs: list[float], lows: list[float], k: int = PIVOT_K) -> list[dict]:
    """分形 pivot: 左右各 k 根内最高的高点/最低的低点。"""
    pivots = []
    n = len(highs)
    for i in range(k, n - k):
        win_h = highs[i - k:i + k + 1]
        win_l = lows[i - k:i + k + 1]
        if highs[i] == max(win_h) and win_h.count(highs[i]) == 1:
            pivots.append({"idx": i, "price": highs[i], "kind": "high"})
        if lows[i] == min(win_l) and win_l.count(lows[i]) == 1:
            pivots.append({"idx": i, "price": lows[i], "kind": "low"})
    return pivots


def cluster_levels(pivots: list[dict], price: float, atr_val: float | None) -> list[dict]:
    """pivot 聚类成支撑/压力位。

    容差 = max(1.5%, 0.8×ATR);「强」= touches ≥ 2(被触及两次以上)。
    阈值为设计选择,输出会标明。
    """
    if not pivots:
        return []
    tol = max(price * 0.015, (atr_val or 0) * 0.8)
    pts = sorted(pivots, key=lambda p: p["price"])
    clusters: list[list[dict]] = [[pts[0]]]
    for p in pts[1:]:
        if p["price"] - clusters[-1][-1]["price"] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = []
    for cl in clusters:
        levels.append({
            "price": sum(p["price"] for p in cl) / len(cl),
            "touches": len(cl),
            "last_idx": max(p["idx"] for p in cl),
        })
    return levels


def cross_below_recently(closes: list[float], level: float, m: int = BROKE_BARS) -> bool:
    return any(closes[i - 1] >= level > closes[i]
               for i in range(max(1, len(closes) - m), len(closes)))


def cross_above_recently(closes: list[float], level: float, m: int = 5) -> bool:
    return any(closes[i - 1] <= level < closes[i]
               for i in range(max(1, len(closes) - m), len(closes)))


def cross_line_below_recently(closes: list[float], line, m: int = 3) -> bool:
    """对逐根变化的趋势线值做「近 m 根内自上而下穿越」检测(捕捉二次跌破)。"""
    n = len(closes)
    return any(closes[i - 1] >= line(i - 1) and closes[i] < line(i)
               for i in range(max(1, n - m), n))


def _line_through(i1: float, p1: float, i2: float, p2: float):
    slope = (p2 - p1) / (i2 - i1) if i2 != i1 else 0.0

    def value(i: float) -> float:
        return p1 + slope * (i - i1)
    return slope, value


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


# ---------------------------------------------------------------------------
# 特征提取(纯函数)
# ---------------------------------------------------------------------------

def build_features(bars: list[dict]) -> dict:
    """bars: 按时间升序的 [{open,close,high,low,volume}],至少 30 根。"""
    c = [float(b["close"]) for b in bars]
    o = [float(b["open"]) for b in bars]
    h = [float(b["high"]) for b in bars]
    l = [float(b["low"]) for b in bars]
    v = [float(b.get("volume") or 0) for b in bars]
    n = len(c)
    last = c[-1]

    vol_ma5 = rolling_mean(v, 5)
    ma5, ma10 = sma_series(c, 5), sma_series(c, 10)
    ma20, ma60 = sma_series(c, 20), sma_series(c, 60)
    r6 = rsi_series(c, 6)
    atr14 = _atr(h, l, c, 14) or max(last * 0.02, 1e-6)

    pivots = find_pivots(h, l)
    levels = cluster_levels(pivots, last, atr14)
    # 剔除「最近 7 根内才首次出现的单一极值」——突破棒/破位棒自己刚创出的
    # 极值不是有效压力/支撑(B1 突破后的上方空间不应被突破棒自身高点封顶)。
    # 但被触碰 ≥2 次的结构位(含刚被回踩测试的历史强支撑)必须保留:
    # 回踩强支撑企稳正是 B1 类最优买点,不能因最近一次触碰把它整簇丢掉
    levels = [x for x in levels if x["touches"] >= 2 or x["last_idx"] <= n - 7]
    supports = sorted([x for x in levels if x["price"] < last * 0.999],
                      key=lambda x: -x["price"])
    resistances = sorted([x for x in levels if x["price"] > last * 1.001],
                         key=lambda x: x["price"])
    sup = supports[0] if supports else None
    res = resistances[0] if resistances else None

    # 止损/目标与盈亏比(B0/D5/U4 共用)
    stop = sup["price"] if sup else None
    target = res["price"] if res else None
    stop_dist = (last - stop) / last if stop else None
    rr = round((target - last) / (last - stop), 2) if stop and target and last > stop else None

    # 趋势背景
    m20_now, m20_prev = ma20[-1], ma20[-8]
    if m20_now is None or m20_prev is None:
        context = "震荡"
    elif last > m20_now and m20_now >= m20_prev:
        context = "上涨过程"
    elif last < m20_now and m20_now <= m20_prev:
        context = "下跌过程"
    else:
        context = "震荡"

    # 主要上行波段 → 斐波那契回撤(D3/B9)
    win = min(n, 250)
    lo_i = min(range(n - win, n), key=lambda i: l[i])
    hi_i = max(range(lo_i, n), key=lambda i: h[i])
    fib = None
    if hi_i > lo_i and (h[hi_i] - l[lo_i]) / max(l[lo_i], 1e-9) >= 0.15 and hi_i >= n - 120:
        rng = h[hi_i] - l[lo_i]
        fib = {"low": l[lo_i], "high": h[hi_i], "hi_idx": hi_i,
               "f382": h[hi_i] - 0.382 * rng, "f50": h[hi_i] - 0.5 * rng,
               "f618": h[hi_i] - 0.618 * rng}

    # 背离(基于 pivot 与 RSI6)。时效约束: 第二个 pivot 必须在近 25 根内
    # (陈年背离不作数),且两 pivot 跨度 ≤40 根(跨季度的 pivots 不构成背离)
    def _div(piv_kind: str, bearish: bool) -> dict | None:
        pts = [p for p in pivots if p["kind"] == piv_kind and r6[p["idx"]] is not None]
        if len(pts) < 2:
            return None
        a, b = pts[-2], pts[-1]
        if b["idx"] - a["idx"] < 4 or b["idx"] - a["idx"] > 40 or b["idx"] < n - 25:
            return None
        if bearish:
            ok = b["price"] > a["price"] and r6[b["idx"]] < r6[a["idx"]] - 2
        else:
            ok = b["price"] < a["price"] and r6[b["idx"]] > r6[a["idx"]] + 2
        if ok:
            return {"idx1": a["idx"], "p1": a["price"], "r1": r6[a["idx"]],
                    "idx2": b["idx"], "p2": b["price"], "r2": r6[b["idx"]]}
        return None

    dd250 = 1 - last / max(h) if max(h) > 0 else 0.0

    return {
        "n": n, "o": o, "c": c, "h": h, "l": l, "v": v,
        "last": last, "vol_ma5": vol_ma5, "ma5": ma5, "ma10": ma10,
        "ma20": ma20, "ma60": ma60, "rsi6": r6,
        "rsi6_last": r6[-1], "atr": atr14, "atr_pct": atr14 / last,
        "pivots": pivots, "levels": levels, "supports": supports,
        "resistances": resistances, "support": sup, "resistance": res,
        "stop": stop, "target": target, "stop_dist": stop_dist, "rr": rr,
        "context": context, "fib": fib,
        "bearish_div": _div("high", True), "bullish_div": _div("low", False),
        "dd250": dd250, "piv_highs": [p for p in pivots if p["kind"] == "high"],
        "piv_lows": [p for p in pivots if p["kind"] == "low"],
    }


# ---------------------------------------------------------------------------
# 规则引擎:每条规则返回 {status, evidence}
#   不买规则 status: triggered / clear / manual / na
#   买点规则 status: matched / none / manual; B0: pass / fail / manual
# ---------------------------------------------------------------------------

def _r(status: str, evidence: str) -> dict:
    return {"status": status, "evidence": evidence}


def check_rules(f: dict, opts: dict | None = None) -> dict:
    opts = opts or {}
    lb = int(opts.get("lookback") or 60)
    max_stop = float(opts.get("max_stop_pct") or 8.0)
    n, c, o, h, l, v = f["n"], f["c"], f["o"], f["h"], f["l"], f["v"]
    last = f["last"]
    vol5 = f["vol_ma5"]
    R: dict[str, dict] = {}

    # ---- 下跌过程 12 不买 ----
    prior_min = min(c[max(0, n - lb - 1):-1]) if n > 5 else c[0]
    R["D1"] = _r("triggered" if last <= prior_min * 1.001 else "clear",
                 f"最新收盘 {last:.2f} vs 近{lb}日最低收盘 {prior_min:.2f}")

    # D2: 刚跌破强支撑 + 上方压力距离 ≤4%
    # 注意「被跌破的支撑」此刻位于现价上方(归入 levels/resistances 一侧),
    # 必须扫全量 levels,不能只扫 supports
    broken = [x for x in f["levels"]
              if x["price"] > last and cross_below_recently(c, x["price"])]
    broke_strong = [x for x in broken if x["touches"] >= 2]
    res = f["resistance"]
    near_res = res is not None and (res["price"] - last) / last <= NEAR_RES_PCT
    if broke_strong and near_res:
        R["D2"] = _r("triggered", f"近{BROKE_BARS}日跌破强支撑 "
                     f"{broke_strong[0]['price']:.2f}(触及{broke_strong[0]['touches']}次),"
                     f"上方压力 {res['price']:.2f}(距现价 {pct((res['price'] - last) / last)})")
    elif broke_strong:
        R["D2"] = _r("clear", "跌破强支撑但上方压力尚远")
    else:
        R["D2"] = _r("clear", "近几日未跌破强支撑")

    # D3: 刚跌破 上行趋势线 / 斐波那契61.8% / 结构颈线
    # (均用穿越式检测: 近 3 根内发生自上而下交叉即算,含「跌破→反抽→二次跌破」)
    breaks = []
    lows_p = f["piv_lows"]
    if len(lows_p) >= 2:
        a, b = lows_p[-2], lows_p[-1]
        if b["price"] > a["price"] and b["idx"] > a["idx"]:  # 上行趋势线(低点抬高)
            _, line = _line_through(a["idx"], a["price"], b["idx"], b["price"])
            if cross_line_below_recently(c, line):
                breaks.append(f"上行趋势线(现值 {line(n - 1):.2f})")
    if f["fib"] and cross_below_recently(c, f["fib"]["f618"]):
        breaks.append(f"斐波那契61.8%({f['fib']['f618']:.2f})")
    # 颈线/强支撑跌破: 同 D2,被跌破的位在现价上方,须扫全量 levels
    neck = [x for x in f["levels"]
            if x["price"] > last and x["touches"] >= 2 and cross_below_recently(c, x["price"])]
    if neck:
        breaks.append(f"结构颈线/强支撑 {neck[0]['price']:.2f}")
    R["D3"] = _r("triggered" if breaks else "clear",
                 "、".join(breaks) if breaks else "未发生关键位跌破")

    # D4: 缩量反弹(反弹 + 仍处弱势区 + 缩量)
    weak_pos = (f["ma20"][-1] is not None and last < f["ma20"][-1]) or f["dd250"] >= 0.10
    shrink_now = vol5[-1] is not None and v[-1] < SHRINK_VOL * vol5[-1]
    rebound = last > c[-2]
    R["D4"] = _r("triggered" if (rebound and weak_pos and shrink_now) else "clear",
                 f"今日{'反弹' if rebound else '未反弹'},量比 "
                 f"{(v[-1] / vol5[-1]) if vol5[-1] else 0:.2f},"
                 f"{'处弱势区' if weak_pos else '非弱势区'}")

    # D5(与 U4 同引擎): 止损可判定性 / 距离是否在承受力内
    if f["stop"] is None:
        stop_ev = "下方无明确支撑位,无法确定止损"
        stop_status = "triggered"
    else:
        d = f["stop_dist"] * 100
        stop_ev = f"建议止损 {f['stop']:.2f}(距现价 {d:.1f}%),承受力上限 {max_stop:.0f}%"
        stop_status = "triggered" if d > max_stop else "clear"
    R["D5"] = _r(stop_status, stop_ev)
    R["U4"] = _r(stop_status, stop_ev)

    # D6: 昨日板块内跌幅排名(人工,可答)
    ans = opts.get("sector_top_decline")
    R["D6"] = (_r("triggered", "确认昨日板块内跌幅居前10%") if ans == "yes"
               else _r("clear", "确认昨日板块内跌幅未居前10%") if ans == "no"
               else _r("manual", "昨日该股在所属板块内跌幅是否排前10%?(30只成分≈前3)"
                       " 用 --sector-top-decline yes/no 回答"))

    # D7: 持续下跌 + 财报前跌幅异常放大
    ed = opts.get("earnings_days")
    drop = (last - c[-2]) / c[-2] if n > 1 and c[-2] else 0.0
    abnormal = drop <= -0.04 or drop <= -(1.8 * f["atr_pct"])
    if ed is None:
        R["D7"] = _r("manual", "财报日期未知(可用 --earnings-days N 指定)"
                     f";今日涨跌 {pct(drop)}")
    elif f["context"] == "下跌过程" and ed <= 10 and abnormal:
        R["D7"] = _r("triggered", f"下跌趋势中,{ed} 天后财报,今日跌幅 {pct(drop)}"
                     f" 异常放大(ATR≈{pct(f['atr_pct'])})")
    else:
        R["D7"] = _r("clear", f"距财报 {ed} 天,今日涨跌 {pct(drop)}")

    # D8: 刚止损不久(人工,可答)
    ans = opts.get("recent_stopout")
    R["D8"] = (_r("triggered", "确认近期刚对该股(或同标的)止损过") if ans == "yes"
               else _r("clear", "确认近期未止损") if ans == "no"
               else _r("manual", "是否刚刚止损不久(同一标的或同一形态连续止损)?"
                       " 用 --recent-stopout yes/no 回答"))

    # D9: 不熟悉 / 累计跌幅过大(半自动: 跌幅可算,熟悉度人工)
    deep = f["dd250"] >= 0.45
    fam = opts.get("familiar")
    if deep or fam == "no":
        why = []
        if deep:
            why.append(f"距最高点累计回撤 {pct(f['dd250'])} ≥45%")
        if fam == "no":
            why.append("确认不熟悉该标的")
        R["D9"] = _r("triggered", ";".join(why))
    elif fam == "yes":
        R["D9"] = _r("clear", f"确认熟悉;累计回撤 {pct(f['dd250'])}")
    else:
        R["D9"] = _r("manual", f"累计回撤 {pct(f['dd250'])};是否熟悉该标的?"
                     " 用 --familiar yes/no 回答")

    # D10: 大跌后社群热度飙升的小市值(热度榜 + 市值自动;小市值是必要条件)
    in_heat = opts.get("in_heat")
    smallcap = opts.get("smallcap")  # True/False/None(查询失败)
    d5 = (last - c[-6]) / c[-6] if n > 6 and c[-6] else 0.0
    if in_heat is None:
        R["D10"] = _r("manual", "热度榜数据不可用;该股是否刚经历大跌且社群热度飙升?"
                      " 市值是否偏小?")
    elif in_heat and d5 <= -0.08 and smallcap is False:
        R["D10"] = _r("clear", f"热度榜命中且近5日跌幅 {pct(d5)},"
                      "但为大市值股,非小市值炒作形态")
    elif in_heat and d5 <= -0.08:
        ev = f"该股进入热度榜且近5日跌幅 {pct(d5)}"
        ev += ";小市值(总股本×现价 < 阈值)" if smallcap else \
            ";市值未知,请自行确认是否小市值"
        R["D10"] = _r("triggered", ev)
    else:
        R["D10"] = _r("clear", f"热度榜{'命中' if in_heat else '未命中'};"
                      f"近5日涨跌 {pct(d5)}")

    # D11: 盘前盘后非财报消息面异动(人工,可答)
    ans = opts.get("prepost_move")
    R["D11"] = (_r("triggered", "确认盘前/盘后因非财报消息大涨大跌") if ans == "yes"
                else _r("clear", "确认盘前/盘后无异动") if ans == "no"
                else _r("manual", "盘前/盘后是否有非财报消息面的大涨大跌?"
                        " 用 --prepost-move yes/no 回答"))

    # D12: 开盘后前 30 分钟(按市场当地时钟推算;原文「开盘前半小时」按开盘后
    #      首 30 分钟纪律执行,与 D11 的盘前盘后互不重叠)
    R["D12"] = _check_open_window(opts)

    # ---- 上涨过程 6 不买 ----
    prior_max = max(c[max(0, n - lb - 1):-1]) if n > 5 else c[0]
    new_high_lb = last >= prior_max * 0.999
    R["U1"] = _r("triggered" if (new_high_lb and shrink_now) else "clear",
                 f"近{lb}日新高: {'是' if new_high_lb else '否'},量比 "
                 f"{(v[-1] / vol5[-1]) if vol5[-1] else 0:.2f}")

    new_high_all = last >= max(c[:-1]) * 0.999
    below = [x["price"] for x in f["supports"]] + [m for m in (f["ma20"][-1], f["ma10"][-1])
                                                   if m and m < last]
    near_sup = max(below) if below else None
    sup_dist = (last - near_sup) / last if near_sup else 1.0
    R["U2"] = _r("triggered" if (new_high_all and sup_dist > 0.10) else "clear",
                 f"区间新高: {'是' if new_high_all else '否'};"
                 f"最近支撑 {near_sup:.2f} 距 {pct(sup_dist)}" if near_sup
                 else f"区间新高: {'是' if new_high_all else '否'};下方无参考支撑")

    broke_up = any(cross_above_recently(c, x["price"]) for x in f["levels"])
    strong_res = [x for x in f["resistances"] if x["touches"] >= 2]
    nxt = strong_res[0] if strong_res else None
    if broke_up and nxt and (nxt["price"] - last) / last <= 0.03:
        R["U3"] = _r("triggered", f"近期刚突破压力,下一强压力 {nxt['price']:.2f}"
                     f" 距 {pct((nxt['price'] - last) / last)}")
    else:
        R["U3"] = _r("clear", "未触发(或上方已无强压力)")

    r6 = f["rsi6_last"]
    R["U5"] = _r("triggered" if (r6 is not None and r6 > 90) else "clear",
                 f"RSI(6) = {r6:.1f}" if r6 is not None else "RSI 数据不足")

    div = f["bearish_div"]
    r6_txt = f"RSI(6) = {r6:.1f}" if r6 is not None else "RSI 数据不足"
    R["U6"] = _r("triggered" if (r6 is not None and r6 > 80 and div) else "clear",
                 f"{r6_txt};顶背离: {'有(价升RSI降)' if div else '无'}")

    # ---- 高胜率买点 ----
    # B0: 盈亏比闸门
    if f["rr"] is None:
        if f["stop"] is None and f["target"] is None:
            R["B0"] = _r("manual", "无结构位参考,盈亏比无法计算")
        elif f["stop"] is None:
            R["B0"] = _r("manual", f"下方无支撑,止损无法定;目标 {f['target']:.2f}")
        else:
            R["B0"] = _r("manual", f"止损 {f['stop']:.2f};上方无结构压力"
                          "(空间最优情形),按自定目标核算盈亏比 ≥1:1")
    else:
        R["B0"] = _r("pass" if f["rr"] >= 1.0 else "fail",
                     f"目标 {f['target']:.2f}(压力) / 止损 {f['stop']:.2f}(支撑)"
                     f" → 盈亏比 1:{f['rr']:.2f}")

    R["B1"] = _check_b1(f)
    R["B2"] = _check_b2(f)
    R["B3"] = _check_b3(f)
    R["B4"] = _check_b4(f)
    R["B5"] = _check_b5(f)
    R["B6"] = _check_b6(f)
    R["B7"] = _check_b7(f)
    R["B8"] = _check_b8(f, opts)
    R["B9"] = _check_b9(f)

    # B 规则的 manual(如 B8 待确认板块)也要进人工清单,不能被结论吞没;
    # B0 闸门的 manual 不阻断、单列在 gate 里,不重复计入
    triggered = [k for k in RULE_NAMES if R[k]["status"] == "triggered"]
    manual = [k for k in RULE_NAMES if R[k]["status"] == "manual" and k != "B0"]
    matched = [k for k in R if k.startswith("B") and k != "B0"
               and R[k]["status"] == "matched"]
    b_pending = [k for k in manual if k.startswith("B")]
    gate_fail = R["B0"]["status"] == "fail"

    reasons = [f"{k} {RULE_NAMES[k]}({R[k]['evidence'][:40]})" for k in triggered]
    if gate_fail:
        reasons.append(f"B0 {R['B0']['evidence']}")
    if reasons:
        verdict, v_reasons = "❌ 不买", reasons
    elif matched:
        verdict = "✅ 结构符合(纪律通过)"
        v_reasons = [f"{k} {RULE_NAMES[k]}" for k in matched]
    elif b_pending:
        verdict = "⏸️ 观望(潜在买点待确认)"
        v_reasons = [f"潜在买点待确认: {','.join(b_pending)}"
                     "(回答对应 CLI 参数后复跑)"]
    else:
        verdict, v_reasons = "⏸️ 观望", ["未出现任何高胜率买点结构"]
    if manual and verdict != "❌ 不买":
        v_reasons = v_reasons + [f"待人工确认: {','.join(manual)}"]

    return {"context": f["context"], "rules": R, "triggered": triggered,
            "manual": manual, "matched": matched, "gate": R["B0"],
            "verdict": verdict, "verdict_reasons": v_reasons}


# ---------------------------------------------------------------------------
# 各买点结构检测(B1-B9)
# ---------------------------------------------------------------------------

def _check_b1(f: dict) -> dict:
    """放量突破前高/强压力 → 缩量回踩不破。"""
    n, c, v, h = f["n"], f["c"], f["v"], f["h"]
    vol5 = f["vol_ma5"]
    ph = f["piv_highs"]
    for b in range(max(5, n - 12), n):
        prior = [p["price"] for p in ph if b - 60 <= p["idx"] < b]
        level = max(prior) if prior else max(h[max(0, b - 20):b])
        if not (v[b] >= EXPAND_VOL * (vol5[b] or v[b]) and c[b] > level):
            continue
        after = list(range(b + 1, n))
        if len(after) < 1:
            continue
        holds = all(c[i] >= level * 0.99 for i in after)
        pulled = min(c[i] for i in after) < c[b]
        shrink = max(v[i] for i in after) < v[b] if after else False
        near = level <= c[-1] <= c[b] * 1.05
        if holds and pulled and shrink and near:
            return _r("matched", f"第{b}根放量突破 {level:.2f} 后缩量回踩不破,"
                      "上方压力情况决定空间")
    return _r("none", "未检出「放量突破+缩量回踩」结构")


def _check_b2(f: dict) -> dict:
    """下降趋势线放量突破 → 缩量回踩收盘不跌回线下。"""
    n, c, v = f["n"], f["c"], f["v"]
    vol5 = f["vol_ma5"]
    ph = f["piv_highs"]
    if len(ph) < 2:
        return _r("none", "pivot 不足,无法拟合下降趋势线")
    a, b = ph[-2], ph[-1]
    if not (a["idx"] < b["idx"] and b["price"] < a["price"] * 0.98):
        return _r("none", "近期高点未走低,无下降趋势线")
    slope, line = _line_through(a["idx"], a["price"], b["idx"], b["price"])
    # i ≤ n-2: 突破后至少要有一根回踩棒——突破当天不能自称「回踩不破」
    for i in range(max(1, n - 8), n - 1):
        if c[i] > line(i) and c[i - 1] <= line(i - 1) and v[i] >= 1.2 * (vol5[i] or v[i]):
            if all(c[j] >= line(j) * 0.998 for j in range(i, n)):
                return _r("matched", f"放量突破下降趋势线(斜率{slope:.3f})后回踩,"
                          "收盘未跌回线下")
    return _r("none", "未检出趋势线突破回踩结构")


def _check_b3(f: dict) -> dict:
    """上升旗形: 旗杆(3根+连涨≥8%) → 旗面(3-8根缩量阴跌,不破杆顶) → 放量过旗面。"""
    n, c, v, h = f["n"], f["c"], f["v"], f["h"]
    vol5 = f["vol_ma5"]
    for s in range(max(0, n - 20), n - 8):
        e = s
        while e + 1 < n and c[e + 1] > c[e]:
            e += 1
        pole_len = e - s + 1
        if pole_len < 3 or c[e] / c[s] - 1 < 0.08:
            continue
        flag = list(range(e + 1, n - 1))  # 旗面不含最后突破棒
        if not 3 <= len(flag) <= 8:
            continue
        if max(h[e + 1:n - 1]) > h[e] * 1.005:
            continue  # 旗面创了新高,不是旗形
        if c[n - 2] < c[e] - 0.4 * (c[e] - c[s]):
            continue  # 回撤过深
        if sum(v[e + 1:n - 1]) / len(flag) >= 0.85 * sum(v[s:e + 1]) / pole_len:
            continue  # 旗面未缩量
        if c[-1] > max(h[e + 1:n - 1]) and v[-1] >= 1.2 * (vol5[-1] or v[-1]):
            return _r("matched", f"旗杆{pole_len}根涨{pct(c[e] / c[s] - 1)},旗面"
                      f"{len(flag)}根缩量整理,今放量破旗面")
    return _r("none", "未检出上升旗形结构")


def _check_b4(f: dict) -> dict:
    """W底/双底: 颈线放量突破 → 回踩不破颈线。"""
    n, c, v, h = f["n"], f["c"], f["v"], f["h"]
    vol5 = f["vol_ma5"]
    pl = f["piv_lows"]
    pair = None
    for i in range(len(pl) - 1):
        a, b = pl[i], pl[i + 1]
        if b["idx"] - a["idx"] >= 5 and b["idx"] >= n - 25:
            if abs(b["price"] - a["price"]) / min(a["price"], b["price"]) <= 0.04:
                pair = (a, b)
    if not pair:
        return _r("none", "未检出双重底结构")
    a, b = pair
    neck = max(h[a["idx"] + 1:b["idx"]])
    for i in range(max(b["idx"] + 2, n - 10), n):
        if c[i] > neck and v[i] >= 1.4 * (vol5[i] or v[i]):
            after = list(range(i + 1, n))
            if not after:
                continue  # 突破棒就是最新一根,回踩尚未发生
            if all(c[j] >= neck * 0.99 for j in after) and \
               any(f["l"][j] <= neck * 1.03 for j in after):
                return _r("matched", f"双底 {a['price']:.2f}/{b['price']:.2f},颈线"
                          f" {neck:.2f} 放量突破后回踩不破")
    return _r("none", "有双底雏形但无有效颈线突破回踩")


def _check_b5(f: dict) -> dict:
    """连续上涨后第一次回踩 5/10 日线不破,买盘明显。"""
    n, c, o, l = f["n"], f["c"], f["o"], f["l"]
    ma5, ma10, ma20 = f["ma5"], f["ma10"], f["ma20"]
    if not (ma5[-1] and ma10[-1] and ma20[-1]):
        return _r("na", "均线数据不足")
    if not (ma5[-1] > ma10[-1] > ma20[-1] and c[-1] > ma20[-1]):
        return _r("none", "非多头排列(5>10>20),不符合前提")
    if n <= 11 or c[n - 6] <= c[n - 11]:
        return _r("none", "前期非连续上涨")
    run = 0
    for i in range(n - 1, 0, -1):
        if c[i] < c[i - 1]:
            run += 1
        else:
            break
    if run > 2:
        return _r("none", f"已连续 {run} 根阴跌至均线(非首次回踩)")
    touched = [m for m in (ma5[-1], ma10[-1]) if l[-1] <= m]
    if not touched:
        return _r("none", "未回踩到 5/10 日线")
    # 守住「触及的最深一根」均线即可: 经典 10 日线回踩会同时下穿 5 日线,
    # 若要求收在 5 日线上方,10 日线回踩结构永远无法成立
    deepest = touched[-1]
    held = c[-1] >= deepest
    body = abs(c[-1] - o[-1])
    lower = min(c[-1], o[-1]) - l[-1]
    strong_buy = c[-1] > o[-1] or lower >= 0.5 * body
    if held and strong_buy:
        which = "10日" if deepest == ma10[-1] else "5日"
        return _r("matched", f"多头排列首次回踩{which}线不破,"
                  f"{'收阳' if c[-1] > o[-1] else '下影抵抗'}")
    return _r("none", "回踩均线但收盘未守住")


def _check_b6(f: dict) -> dict:
    """缩量阴线创近期低点 → 放量看涨吞没大阳线(上影短)。"""
    c, o, v = f["c"], f["o"], f["v"]
    n = f["n"]
    vol5 = f["vol_ma5"]
    p = n - 2
    if p < 1:
        return _r("na", "数据不足")
    shrink = vol5[p] and v[p] < SHRINK_VOL * vol5[p]
    at_low = c[p] <= min(c[max(0, p - 10):p]) * 1.001
    down = c[p] < o[p]
    if not (shrink and at_low and down):
        return _r("none", "前一日非「缩量阴线创近期低点」")
    body = c[-1] - o[-1]
    avg_body = sum(abs(c[i] - o[i]) for i in range(max(0, n - 11), n - 1)) / 10
    upper = f["h"][-1] - max(c[-1], o[-1])
    engulf = o[-1] <= c[p] and c[-1] >= o[p]
    vol_ok = vol5[-1] is not None and v[-1] >= 1.2 * vol5[-1]  # 「放量」落到实处
    if engulf and body >= 1.5 * max(avg_body, 1e-9) and \
       upper <= 0.3 * max(body, 1e-9) and vol_ok:
        return _r("matched", f"放量吞没大阳(实体约为均体 {body / max(avg_body, 1e-9):.1f} 倍,"
                  f"量比 {v[-1] / vol5[-1]:.1f},上影短)")
    return _r("none", "当日无有效放量看涨吞没")


def _check_b7(f: dict) -> dict:
    """缩量阴线创近期低点 → 标准放量锤子线(下影≥2倍实体,上影极短)。"""
    c, o, v, h, l = f["c"], f["o"], f["v"], f["h"], f["l"]
    n = f["n"]
    vol5 = f["vol_ma5"]
    p = n - 2
    if p < 1:
        return _r("na", "数据不足")
    shrink = vol5[p] and v[p] < SHRINK_VOL * vol5[p]
    at_low = c[p] <= min(c[max(0, p - 10):p]) * 1.001
    down = c[p] < o[p]
    if not (shrink and at_low and down):
        return _r("none", "前一日非「缩量阴线创新低」")
    body = abs(c[-1] - o[-1])
    if body <= 0:
        return _r("none", "十字星,非标准锤子")
    lower = min(c[-1], o[-1]) - l[-1]
    upper = h[-1] - max(c[-1], o[-1])
    rng = h[-1] - l[-1]
    vol_ok = vol5[-1] and v[-1] >= 1.2 * vol5[-1]
    if lower >= 2 * body and upper <= 0.35 * body and rng > 0 and \
       (c[-1] - l[-1]) / rng >= 0.6 and vol_ok:
        return _r("matched", f"标准锤子线(下影 {lower / body:.1f} 倍实体)且放量,"
                  "止跌形态有效性排序第一")
    return _r("none", "当日无标准放量锤子线")


def _check_b8(f: dict, opts: dict) -> dict:
    """板块突破日,成分股放量实体大阳突破最近压力(个股半边自动,板块半边人工)。"""
    c, o, v, h = f["c"], f["o"], f["v"], f["h"]
    n = f["n"]
    vol5 = f["vol_ma5"]
    ok = False
    for b in (n - 1, n - 2):
        if b < 5:
            continue
        prior = [p["price"] for p in f["piv_highs"] if b - 40 <= p["idx"] < b]
        level = max(prior) if prior else max(h[max(0, b - 20):b])
        body = c[b] - o[b]
        upper = h[b] - max(c[b], o[b])
        if v[b] >= EXPAND_VOL * (vol5[b] or v[b]) and body > 0 and \
           body / c[b] >= 0.03 and upper <= 0.3 * body and c[b] > level:
            ok = True
            break
    if not ok:
        return _r("none", "近两日无「放量实体大阳突破最近压力」")
    ans = opts.get("sector_breakout")
    detail = f"({opts['sector_detail']})" if opts.get("sector_detail") else ""
    if ans == "yes":
        return _r("matched", f"个股放量长阳突破成立,且确认所属板块当日突破{detail}")
    if ans == "no":
        return _r("none", f"个股突破成立但所属板块当日未突破{detail}")
    return _r("manual", "个股放量长阳突破成立;所属板块当日是否突破?"
              " 用 --sector-breakout yes/no 回答,或 --sector <行业名> 自动查")


def _check_b9(f: dict) -> dict:
    """回撤不破斐波那契 + RSI(6)<20 超卖 + 底背离 + 止跌形态,四者齐备。"""
    c, o, h, l = f["c"], f["o"], f["h"], f["l"]
    fib = f["fib"]
    parts = []
    ok_fib = fib is not None and c[-1] >= fib["f618"]
    parts.append(f"回撤守{round(fib['f618'], 2) if fib else 'N/A'}:"
                 f"{'✓' if ok_fib else '✗'}")
    r6 = f["rsi6_last"]
    ok_rsi = r6 is not None and r6 < 20
    parts.append(f"RSI6={r6 and round(r6, 1)}:{'✓' if ok_rsi else '✗'}")
    ok_div = f["bullish_div"] is not None
    parts.append(f"底背离:{'✓' if ok_div else '✗'}")
    body = abs(c[-1] - o[-1])
    lower = min(c[-1], o[-1]) - l[-1]
    candle = (lower >= 1.5 * max(body, 1e-9)) or (c[-1] > o[-1] and c[-2] < o[-2]
                                                   and c[-1] >= o[-2])
    parts.append(f"止跌形态:{'✓' if candle else '✗'}")
    if ok_fib and ok_rsi and ok_div and candle:
        return _r("matched", "、".join(parts) + "(大结构上行未破)")
    return _r("none", "、".join(parts))


def _check_open_window(opts: dict) -> dict:
    """D12: 当前是否处于盘前 30 分钟(当地 9:00-9:30,开盘前最后一根半小时)。

    语义经用户确认:「开盘前半小时不买」= 盘前时段的 30 分钟(US 竞价前夜盘尾声
    9:00-9:30 ET / HK 竞价时段 9:00-9:30),不是开盘后的前 30 分钟。
    周末与 closed-calendar 休市日直接放行;港股台风临时停市不在日历内,自行留意。
    """
    now: datetime | None = opts.get("now")
    market = (opts.get("market") or "US").upper()
    if now is None:
        return _r("manual", "无法获取当前时间,盘前30分钟纪律请自行遵守")
    wd = now.weekday()
    if wd >= 5:
        return _r("clear", f"{'周六' if wd == 5 else '周日'}休市")
    if now.strftime("%Y-%m-%d") in (opts.get("closed_dates") or set()):
        return _r("clear", f"{now.strftime('%Y-%m-%d')} 为休市日")
    t = now.hour * 60 + now.minute
    if market in ("US", "HK"):
        if 9 * 60 <= t < 9 * 60 + 30:
            return _r("triggered", f"当前 {now.hour:02d}:{now.minute:02d}(当地),"
                     "处于盘前30分钟(9:00-9:30)")
        return _r("clear", f"当前 {now.hour:02d}:{now.minute:02d}(当地),"
                 "不在盘前30分钟(9:00-9:30)")
    return _r("manual", f"市场 {market} 开盘时段未内置,请自行判断")


def _market_local_now(symbol: str) -> datetime | None:
    """尽力取市场当地时间(HK=UTC+8;US 用 zoneinfo,失败退 UTC-5)。"""
    now = datetime.utcnow()
    if symbol.upper().endswith(".HK"):
        from datetime import timedelta
        return now + timedelta(hours=8)
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    except Exception:
        from datetime import timedelta
        return now + timedelta(hours=-5)


# ---------------------------------------------------------------------------
# CLI 数据层
# ---------------------------------------------------------------------------

def _days_to_earnings(symbol: str) -> int | None:
    try:
        market = symbol.rsplit(".", 1)[-1] if "." in symbol else "US"
        buckets = get_finance_calendar(category="report", market=market,
                                       symbol=symbol, count=20)
        today = datetime.now().strftime("%Y-%m-%d")
        best = None
        for b in buckets or []:
            for info in b.get("infos", []):
                d = str(info.get("date", "")).replace(".", "-")[:10]
                try:
                    days = (datetime.strptime(d, "%Y-%m-%d")
                            - datetime.strptime(today, "%Y-%m-%d")).days
                except ValueError:
                    continue
                if days >= 0 and (best is None or days < best):
                    best = days
        return best
    except Exception:
        return None


def _in_heat_rank(symbol: str) -> bool | None:
    try:
        market = "HK" if symbol.upper().endswith(".HK") else "US"
        keys = get_heat_rank_keys(market)
        if is_empty(keys):
            return None
        data = get_heat_rank(keys[0].get("key") if isinstance(keys[0], dict) else keys[0],
                             count=20)
        # get_heat_rank 返回 {bmp, updated_at, lists:[...]}(键名是复数 lists)
        items = data.get("lists") or data.get("list") or data.get("items") or []
        for it in items:
            s = str(it.get("symbol") or it.get("counter_id") or "")
            if s and s.upper().split(".")[0] == symbol.upper().split(".")[0]:
                return True
        return False
    except Exception:
        return None


def _closed_dates(market: str) -> set[str]:
    """近端休市日(closed-calendar),D12 排除节假日。失败返回空集(仅剩周末规则)。"""
    try:
        buckets = get_finance_calendar(category="closed", market=market, count=30)
        out: set[str] = set()
        for b in buckets or []:
            for info in b.get("infos", []):
                ext = info.get("ext") or {}
                d = str(ext.get("holiday_date") or b.get("date") or "")[:10]
                d = d.replace(".", "-")
                if len(d) == 10:
                    out.add(d)
        return out
    except Exception:
        return set()


def _is_small_cap(symbol: str, threshold_usd: float,
                  price: float | None = None) -> bool | None:
    """static 的 total_shares × 现价;HK 按 7.8 折算美元。失败返回 None。"""
    try:
        rows = normalize_records(run_cli("static", symbol))
        if not rows:
            return None
        shares = to_float(rows[0].get("total_shares"))
        px = price or get_underlying_price(symbol)
        if not shares or not px:
            return None
        cap = shares * px
        if symbol.upper().endswith(".HK"):
            cap /= 7.8
        return cap < threshold_usd
    except Exception:
        return None


def _auto_sector_breakout(symbol: str, market: str, sector: str | None,
                          chg_pct: float) -> tuple[str | None, str]:
    """B8 板块半边自动化: industry-rank 当日板块涨幅榜。

    ⚠️ 实测 CLI 无「个股→所属行业」映射命令(industry-peers 只吃 BK 码,
    quote/static/anomaly/compare 均无行业字段),因此走两条路径:
      ① 用户 --sector <行业名> 指名匹配;
      ② 该股恰为某行业 leading_ticker(领涨股)时反查。
    板块涨幅 ≥ chg_pct 视为「板块突破日」(设计阈值,可 --sector-chg-pct 调整)。
    返回 (yes/no/None, 说明)。
    """
    try:
        rows = get_industry_rank(market=market)
    except Exception:
        return None, "行业排行数据不可用"
    cands = []
    for row in rows or []:
        cands.extend(row.get("lists") or [])
    if sector:
        key = sector.strip().lower()
        hit = next((i for i in cands
                    if key in str(i.get("name", "")).lower()), None)
        if not hit:
            return None, f"当日涨幅榜未见行业「{sector}」"
    else:
        ticker = symbol.split(".")[0].upper()
        hit = next((i for i in cands
                    if str(i.get("leading_ticker", "")).upper() == ticker), None)
        if not hit:
            return None, "无法定位该股所属行业(可用 --sector <行业名> 指定)"
    chg = to_float(hit.get("chg"))
    if chg is None:
        return None, f"行业「{hit.get('name')}」无当日涨幅数据"
    ok = chg >= chg_pct
    return ("yes" if ok else "no",
            f"行业「{hit.get('name')}」今日 {chg * 100:.1f}%,阈值 {chg_pct * 100:.0f}%")


# ---------------------------------------------------------------------------
# 输出渲染
# ---------------------------------------------------------------------------

_ICON = {"triggered": "❌", "clear": "✅", "manual": "❓", "matched": "🎯",
         "none": "—", "pass": "✅", "fail": "❌", "na": "—"}


def render(symbol: str, result: dict, price, generated: str) -> None:
    R = result["rules"]
    print(f"{'=' * 60}")
    print(f"  {symbol} 入场纪律检查(28条军规)  现价 {price}  {generated}")
    print(f"{'=' * 60}")
    print(f"\n  趋势背景: {result['context']}\n")
    print("  ◆ 下跌过程 12 不买:")
    for k in [f"D{i}" for i in range(1, 13)]:
        r = R[k]
        print(f"    {_ICON.get(r['status'], ' ')} [{k}] {RULE_NAMES[k]} — {r['evidence']}")
    print("  ◆ 上涨过程 6 不买:")
    for k in [f"U{i}" for i in range(1, 7)]:
        r = R[k]
        print(f"    {_ICON.get(r['status'], ' ')} [{k}] {RULE_NAMES[k]} — {r['evidence']}")
    print("  ◆ 高胜率买点:")
    for k in [f"B{i}" for i in range(0, 10)]:
        r = R[k]
        print(f"    {_ICON.get(r['status'], ' ')} [{k}] {RULE_NAMES[k]} — {r['evidence']}")
    print(f"\n  {'─' * 56}")
    print(f"  结论: {result['verdict']}")
    for why in result["verdict_reasons"]:
        print(f"    · {why}")
    print(f"\n  ⚠️ 纪律参考非投资建议;形态识别为算法近似,请人工复核。")
    print(f"  人工项回答方式: --sector-top-decline/--recent-stopout/--familiar/")
    print(f"                 --prepost-move/--sector-breakout yes|no;")
    print(f"  B8 板块可 --sector <行业名> 自动查当日涨幅(阈值 --sector-chg-pct)。")


def analyze(symbol: str, args) -> dict:
    bars = get_kline_adjusted(symbol, count=260)
    if len(bars) < 30:
        raise RuntimeError(f"K线不足 30 根(实际 {len(bars)}),无法检查")
    f = build_features(bars)
    market = symbol.rsplit(".", 1)[-1] if "." in symbol else "US"
    opts = {
        "lookback": args.lookback, "max_stop_pct": args.max_stop_pct,
        "sector_top_decline": args.sector_top_decline,
        "recent_stopout": args.recent_stopout,
        "familiar": args.familiar, "prepost_move": args.prepost_move,
        "sector_breakout": args.sector_breakout,
        "earnings_days": args.earnings_days,
        "in_heat": None if args.no_heat else _in_heat_rank(symbol),
        "smallcap": None if args.no_heat else _is_small_cap(symbol, args.smallcap_usd),
        "closed_dates": _closed_dates(market),
        "market": market,
    }
    if args.now:
        opts["now"] = datetime.strptime(args.now, "%Y-%m-%d %H:%M")
    else:
        opts["now"] = _market_local_now(symbol)
    if opts["earnings_days"] is None:
        opts["earnings_days"] = _days_to_earnings(symbol)
    # B8 板块半边: 用户显式回答优先;否则尝试 industry-rank 自动判定
    if not args.sector_breakout:
        ans, note = _auto_sector_breakout(symbol, market, args.sector,
                                          args.sector_chg_pct / 100.0)
        opts["sector_breakout"] = ans
        if note:
            opts["sector_detail"] = note

    result = check_rules(f, opts)
    price = get_underlying_price(symbol) or f["last"]
    result.update({"symbol": symbol, "price": price,
                   "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "levels": {"support": f["stop"], "resistance": f["target"],
                              "rr": f["rr"]},
                   "smallcap": opts["smallcap"],
                   "disclaimer": "纪律清单参考,非投资建议;形态识别为算法近似。"})
    if args.output_json:
        print_json(result)
    else:
        render(symbol, result, price, result["generated_at"])
    return result


# ---------------------------------------------------------------------------
# 离线自检(--demo,无需登录)
# ---------------------------------------------------------------------------

def _bar(o, c, h=None, lo=None, vol=1_000_000):
    return {"open": o, "close": c,
            "high": h if h is not None else max(o, c) * 1.004,
            "low": lo if lo is not None else min(o, c) * 0.996,
            "volume": vol}


def _demo() -> None:
    """三个合成场景: 阴跌新低 / 超买疯涨 / 突破回踩,验证引擎方向性。"""
    scenes = {}

    bars = [_bar(100, 99.8) for _ in range(80)]
    p = 99.0
    for i in range(6):
        bars.append(_bar(p, p - 0.9, vol=900_000 + i * 50_000))
        p -= 0.95
    scenes["阴跌创新低"] = bars

    bars = [_bar(50, 50.2) for _ in range(60)]
    p = 50.5
    for _ in range(25):
        bars.append(_bar(p, p * 1.03, vol=1_500_000))
        p *= 1.03
    scenes["急涨超买"] = bars

    bars = [_bar(99, 100) for _ in range(40)]
    bars[20] = _bar(101, 102, h=103.5, vol=1_200_000)
    bars += [_bar(99.5, 100.2) for _ in range(8)]
    bars.append(_bar(101.5, 105.5, h=106, vol=3_000_000))
    bars += [_bar(104.6, 104.9, vol=1_200_000), _bar(104.4, 104.8, vol=1_100_000),
             _bar(104.5, 105.0, vol=1_000_000)]
    scenes["放量突破后缩量回踩"] = bars

    for name, bs in scenes.items():
        r = check_rules(build_features(bs))
        tri = ",".join(r["triggered"]) or "无"
        mat = ",".join(r["matched"]) or "无"
        print(f"  {name}: 背景={r['context']} 触发不买={tri} 买点={mat}"
              f" → {r['verdict']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="入场纪律检查器(28条军规: 12+6不买 与 10 买点)")
    parser.add_argument("symbol", nargs="?", help="标的代码,如 AAPL.US / 0700.HK")
    parser.add_argument("--json", action="store_true", dest="output_json")
    parser.add_argument("--lookback", type=int, default=60,
                        help="「近期」新低/新高回看天数(默认60)")
    parser.add_argument("--max-stop-pct", type=float, default=8.0,
                        help="止损距离承受力上限%%(默认8,超出判不买)")
    parser.add_argument("--sector-top-decline", choices=["yes", "no"],
                        help="D6: 昨日板块内跌幅是否前10%%")
    parser.add_argument("--recent-stopout", choices=["yes", "no"],
                        help="D8: 是否刚止损不久")
    parser.add_argument("--familiar", choices=["yes", "no"], help="D9: 是否熟悉该标的")
    parser.add_argument("--prepost-move", choices=["yes", "no"],
                        help="D11: 盘前盘后是否有非财报消息面异动")
    parser.add_argument("--sector-breakout", choices=["yes", "no"],
                        help="B8: 所属板块当日是否突破(显式回答,优先于自动判定)")
    parser.add_argument("--sector", help="B8: 指定行业名(如 半导体),自动查当日板块涨幅")
    parser.add_argument("--sector-chg-pct", type=float, default=3.0,
                        help="B8 板块突破阈值%%(默认3,当日板块涨幅≥此值视为突破日)")
    parser.add_argument("--smallcap-usd", type=float, default=2_000_000_000,
                        help="D10 小市值阈值,美元(默认20亿;HK按7.8折算)")
    parser.add_argument("--earnings-days", type=int,
                        help="手动指定距下次财报天数(跳过日历查询)")
    parser.add_argument("--no-heat", action="store_true",
                        help="跳过热度榜与市值查询(D10转人工)")
    parser.add_argument("--now", help="覆盖当前市场当地时间,格式 'YYYY-MM-DD HH:MM'")
    parser.add_argument("--demo", action="store_true", help="离线合成数据自检")
    args = parser.parse_args()

    if args.demo:
        _demo()
        sys.exit(0)
    if not args.symbol:
        parser.error("需要 symbol(或使用 --demo)")
    try:
        analyze(args.symbol, args)
    except Exception as e:
        print_error("入场纪律检查", str(e))
        sys.exit(1)
