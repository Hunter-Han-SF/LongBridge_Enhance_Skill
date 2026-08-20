"""技术面综合评分(0-100,四维加权)。

把 calc_indicators 的全套指标压缩成一个可比对的分数,供快速筛选和
decision/analyze_buy_sell.py 仪表盘复用。

四维设计(权重为设计选择,可按需调整):
  ① 趋势(30 分): MA 排列(15) + 价格 vs MA20(5) + MACD 柱(5) + MACD 金叉(5)
  ② 动量(25 分): RSI 区间(10) + RSI>50(5) + KDJ K>D(5) + ROC20>0(5)
  ③ 量能(20 分): OBV 20期斜率(10) + 量比(5) + MFI 区间(5)
  ④ 位置/波动(25 分): 52周分位适中(10) + 布林带内位置(5) + ATR% 不极端(5)
                      + 20日新高动量(5)

评级: ≥70 强势 / 50-70 偏多 / 30-50 偏弱 / <30 弱势

用法:
    python calc_technical_score.py AAPL.US
    python calc_technical_score.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import print_error, print_json  # noqa: E402
from calc_indicators import compute_all  # noqa: E402


def _score_trend(ind: dict) -> tuple[float, list[str]]:
    s, notes = 0.0, []
    ma, macd_d, price = ind["ma"], ind["macd"], ind["price"]
    ma5, ma20, ma60 = ma.get("ma5"), ma.get("ma20"), ma.get("ma60")
    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            s += 15
            notes.append("MA 多头排列 +15")
        elif ma5 < ma20 < ma60:
            notes.append("MA 空头排列 +0")
        elif ma5 > ma20 or ma5 > ma60:
            s += 8
            notes.append("MA 部分修复 +8")
    if ma20 and price:
        if price > ma20:
            s += 5
            notes.append("价格在 MA20 上方 +5")
    h = macd_d.get("hist")
    if h is not None:
        if h > 0:
            s += 5
            notes.append("MACD 红柱 +5")
        elif h < 0 and macd_d.get("hist_rising"):
            s += 3
            notes.append("MACD 绿柱收缩(修复中)+3")
    if macd_d.get("cross") == "golden":
        s += 5
        notes.append("MACD 金叉 +5")
    return min(s, 30), notes


def _score_momentum(ind: dict) -> tuple[float, list[str]]:
    s, notes = 0.0, []
    r = ind.get("rsi14")
    if r is not None:
        if 50 <= r <= 70:
            s += 10
            notes.append("RSI 健康区(50-70) +10")
        elif 70 < r <= 80:
            s += 6
            notes.append("RSI 偏强但接近超买 +6")
        elif 30 <= r < 50:
            s += 4
            notes.append("RSI 偏弱 +4")
        elif r > 80:
            s += 2
            notes.append("RSI 超买(>80)+2")
        else:
            notes.append("RSI 超卖(<30)+0")
        if r >= 50:
            s += 5
    k9 = ind.get("kdj") or {}
    if k9.get("k") is not None and k9.get("d") is not None and k9["k"] > k9["d"]:
        s += 5
        notes.append("KDJ K>D +5")
    roc20 = ind.get("roc20")
    if roc20 is not None and roc20 > 0:
        s += 5
        notes.append("20日动量为正 +5")
    return min(s, 25), notes


def _score_volume(ind: dict) -> tuple[float, list[str]]:
    s, notes = 0.0, []
    ob = ind.get("obv") or {}
    if ob.get("rising_20"):
        s += 10
        notes.append("OBV 20期上行 +10")
    elif ob.get("rising_20") is False:
        notes.append("OBV 20期下行 +0")
    vr = ind.get("volume_ratio")
    if vr is not None and vr >= 1.0:
        s += 5
        notes.append(f"量比 {vr:.2f}(放量)+5")
    elif vr is not None and vr >= 0.8:
        s += 3
        notes.append(f"量比 {vr:.2f}(温和)+3")
    m = ind.get("mfi14")
    if m is not None:
        if 40 <= m <= 80:
            s += 5
            notes.append("MFI 健康区(40-80) +5")
        elif m > 80:
            s += 2
            notes.append("MFI 超买 +2")
    return min(s, 20), notes


def _score_position(ind: dict) -> tuple[float, list[str]]:
    s, notes = 0.0, []
    pos = ind.get("position_52w") or {}
    p = pos.get("position")
    if p is not None:
        if 20 <= p <= 90:
            s += 10
            notes.append(f"52周分位 {p:.0f}%(趋势与空间兼顾)+10")
        elif p > 90:
            s += 6
            notes.append(f"52周分位 {p:.0f}%(高位,追高风险)+6")
        else:
            s += 3
            notes.append(f"52周分位 {p:.0f}%(低位弱势)+3")
    b = ind.get("bollinger") or {}
    pb = b.get("percent_b")
    if pb is not None:
        if 0.4 <= pb <= 0.9:
            s += 5
            notes.append(f"布林带内位置 {pb:.2f}(中上轨间)+5")
        elif pb > 0.9:
            s += 3
            notes.append(f"布林带内位置 {pb:.2f}(贴上轨)+3")
    ap = ind.get("atr_pct")
    if ap is not None:
        if ap <= 5:
            s += 5
            notes.append(f"ATR {ap:.1f}%/日(波动可控)+5")
        else:
            s += 2
            notes.append(f"ATR {ap:.1f}%/日(波动大)+2")
    dc = ind.get("donchian20") or {}
    if dc.get("upper") and ind["price"] >= dc["upper"]:
        s += 5
        notes.append("突破 20 日新高 +5")
    return min(s, 25), notes


def score(symbol: str, count: int = 300, output_json: bool = False,
          quiet: bool = False) -> dict:
    ind = compute_all(symbol, count=count)
    dims = {
        "趋势": _score_trend(ind),
        "动量": _score_momentum(ind),
        "量能": _score_volume(ind),
        "位置": _score_position(ind),
    }
    total = round(sum(d[0] for d in dims.values()), 1)
    if total >= 70:
        label = "🔥 强势"
    elif total >= 50:
        label = "🟢 偏多"
    elif total >= 30:
        label = "🟡 偏弱"
    else:
        label = "🔴 弱势"

    result = {
        "symbol": symbol,
        "price": ind["price"],
        "technical_score": total,
        "label": label,
        "max_score": 100,
        "dimensions": {
            name: {"score": d[0], "detail": d[1]} for name, d in dims.items()
        },
        "signals": ind["signals"],
        "note": "技术面单维度打分,不含基本面/资金面。权重为设计选择。",
    }

    if output_json:
        print_json(result)
        return result
    if quiet:
        return result

    print(f"{symbol} 技术面综合评分")
    print(f"  总分: {total}/100  {label}")
    for name, d in dims.items():
        print(f"  [{name}] {d[0]:.0f} 分")
        for n in d[1]:
            print(f"      {n}")
    print()
    print("信号:")
    for s_ in result["signals"] or ["(无显著信号)"]:
        print(f"  {s_}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="技术面综合评分(0-100)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US")
    parser.add_argument("--count", type=int, default=300, help="K 线根数(默认 300)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        score(args.symbol, count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("技术面评分", str(e))
        sys.exit(1)
