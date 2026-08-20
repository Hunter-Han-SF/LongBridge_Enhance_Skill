"""全套技术指标计算(MA/MACD/RSI/BOLL/KDJ/ATR/OBV/MFI + 信号检测)。

基于前复权日 K 线(--adjust forward)本地计算,覆盖常用技术面分析需求:
  均线族: MA5/10/20/60/120/250 + EMA12/26
  动量族: MACD(12,26,9), RSI(14), KDJ(9,3,3), ROC(20), Williams %R, CCI(20)
  波动族: Bollinger(20,2), ATR(14)
  量能族: OBV(含20期斜率), MFI(14), 量比
  统计族: 52周位置, 最大回撤, 区间累计收益

信号检测(近几根K线内):
  - MA 多头/空头排列(MA5>MA20>MA60)
  - MA5/MA20 金叉/死叉
  - MACD 金叉/死叉 + 柱体收缩
  - KDJ 金叉/死叉 + 超买超卖(>80/<20)
  - 突破/跌破 20 日唐奇安通道
  - 价格站上/跌破 MA250(年线)

用法:
    python calc_indicators.py AAPL.US
    python calc_indicators.py AAPL.US --count 300 --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    get_kline_adjusted,
    print_display_table,
    print_error,
    print_json,
    to_float,
)
from indicators import (  # noqa: E402
    atr, bollinger, cci, donchian, ema, kdj, macd, mfi, max_drawdown,
    obv, position_in_range, roc, rsi, sma, sma_series, total_return,
    volume_ratio, williams_r,
)

MA_PERIODS = (5, 10, 20, 60, 120, 250)


def compute_all(symbol: str, count: int = 300) -> dict:
    """拉取前复权 K 线并计算全套指标。返回结构化 dict(供其他脚本复用)。"""
    klines = get_kline_adjusted(symbol, count=count)
    closes = [to_float(k.get("close")) for k in klines]
    highs = [to_float(k.get("high")) for k in klines]
    lows = [to_float(k.get("low")) for k in klines]
    vols = [to_float(k.get("volume")) for k in klines]
    if not closes or any(c is None for c in closes[-30:]):
        raise ValueError(f"K 线数据不足,无法计算指标({symbol})")
    closes = [c for c in closes if c is not None]
    highs = [h for h in highs if h is not None]
    lows = [l for l in lows if l is not None]
    vols = [v for v in vols if v is not None]

    price = closes[-1]

    # 均线族
    mas = {f"ma{p}": sma(closes, p) for p in MA_PERIODS}
    emas = {"ema12": ema(closes, 12), "ema26": ema(closes, 26)}

    # 动量/波动/量能/统计
    m = macd(closes)
    k9 = kdj(highs, lows, closes)
    boll = bollinger(closes)
    a = atr(highs, lows, closes)
    ob = obv(closes, vols) if len(vols) == len(closes) else {"obv": None, "slope_20": None, "rising_20": None}
    pos = position_in_range(highs, lows, closes)
    dc = donchian(highs, lows, 20)

    indicators = {
        "symbol": symbol,
        "price": price,
        "bars": len(closes),
        "ma": mas,
        "ema": emas,
        "macd": m,
        "rsi14": rsi(closes),
        "kdj": k9,
        "bollinger": boll,
        "atr14": a,
        "atr_pct": (a / price * 100) if (a and price) else None,
        "obv": ob,
        "mfi14": mfi(highs, lows, closes, vols) if len(vols) == len(closes) else None,
        "volume_ratio": volume_ratio(vols) if len(vols) == len(closes) else None,
        "roc20": roc(closes, 20),
        "williams_r14": williams_r(highs, lows, closes),
        "cci20": cci(highs, lows, closes),
        "position_52w": pos,
        "donchian20": dc,
        "max_drawdown": max_drawdown(closes),
        "total_return_pct": total_return(closes),
    }

    indicators["signals"] = _detect_signals(closes, mas, m, k9, dc, pos)
    return indicators


def _detect_signals(closes: list[float], mas: dict, m: dict, k9: dict,
                    dc: dict, pos: dict) -> list[str]:
    """汇总技术信号(看多/看空),按强度排序。"""
    sig: list[str] = []
    price = closes[-1]
    ma5, ma20, ma60 = mas.get("ma5"), mas.get("ma20"), mas.get("ma60")
    ma250 = mas.get("ma250")

    # 均线排列
    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            sig.append("🟢 MA 多头排列(MA5>MA20>MA60)")
        elif ma5 < ma20 < ma60:
            sig.append("🔴 MA 空头排列(MA5<MA20<MA60)")
    # MA5/20 交叉(近 5 根)
    s5 = sma_series(closes, 5)
    s20 = sma_series(closes, 20)
    for i in range(max(1, len(closes) - 5), len(closes)):
        a0, b0 = s5[i - 1], s20[i - 1]
        a1, b1 = s5[i], s20[i]
        if None not in (a0, b0, a1, b1):
            if a0 <= b0 and a1 > b1:
                sig.append("🟢 MA5/MA20 金叉(近5根)")
            elif a0 >= b0 and a1 < b1:
                sig.append("🔴 MA5/MA20 死叉(近5根)")
    # 年线
    if ma250 and price:
        sig.append("🟢 价格站上 MA250 年线" if price > ma250 else "🔴 价格跌破 MA250 年线")
    # MACD
    if m.get("cross") == "golden":
        sig.append("🟢 MACD 金叉(近3根)")
    elif m.get("cross") == "death":
        sig.append("🔴 MACD 死叉(近3根)")
    if m.get("hist") is not None:
        if m["hist"] > 0 and m.get("hist_rising"):
            sig.append("🟢 MACD 红柱扩张")
        elif m["hist"] < 0 and m.get("hist_rising") is False:
            sig.append("🔴 MACD 绿柱扩张")
    # KDJ
    if k9.get("cross") == "golden":
        sig.append("🟢 KDJ 金叉")
    elif k9.get("cross") == "death":
        sig.append("🔴 KDJ 死叉")
    if k9.get("k") is not None:
        if k9["k"] > 80:
            sig.append("🟡 KDJ 超买(>80,注意回调)")
        elif k9["k"] < 20:
            sig.append("🟡 KDJ 超卖(<20,注意反弹)")
    # 通道突破
    if dc.get("upper") and closes[-1] >= dc["upper"]:
        sig.append("🟢 突破 20 日新高")
    if dc.get("lower") and closes[-1] <= dc["lower"]:
        sig.append("🔴 跌破 20 日新低")
    # 52 周位置
    p = pos.get("position")
    if p is not None:
        if pos.get("near_high"):
            sig.append("🟡 逼近 52 周新高(动量强,但注意追高风险)")
        elif pos.get("near_low"):
            sig.append("🟡 贴近 52 周新低(超跌,需确认反转)")
    return sig


def show_indicators(symbol: str, count: int = 300, output_json: bool = False) -> dict:
    ind = compute_all(symbol, count=count)

    if output_json:
        print_json(ind)
        return ind

    print(f"{symbol} 技术指标全景(现价 {ind['price']},{ind['bars']} 根日K,前复权)")
    print()
    print("【均线】")
    ma_rows = [{"均线": k.upper(), "值": round(v, 2) if v else "N/A",
                "价格位置": "上方 🟢" if (v and ind["price"] > v) else "下方 🔴"}
               for k, v in ind["ma"].items()]
    print_display_table(ma_rows, columns=["均线", "值", "价格位置"])
    print()
    print("【动量】")
    m, k9, b = ind["macd"], ind["kdj"], ind["bollinger"]
    rows = [
        {"指标": "MACD(12,26,9)", "值": f"DIF={m['dif']:.3f} DEA={m['dea']:.3f} 柱={m['hist']:.3f}"},
        {"指标": "RSI(14)", "值": f"{ind['rsi14']:.1f}" if ind["rsi14"] is not None else "N/A"},
        {"指标": "KDJ(9,3,3)", "值": f"K={k9['k']:.1f} D={k9['d']:.1f} J={k9['j']:.1f}"},
        {"指标": "ROC(20)", "值": f"{ind['roc20']:.2f}%" if ind["roc20"] is not None else "N/A"},
        {"指标": "Williams %R", "值": f"{ind['williams_r14']:.1f}" if ind["williams_r14"] is not None else "N/A"},
        {"指标": "CCI(20)", "值": f"{ind['cci20']:.1f}" if ind["cci20"] is not None else "N/A"},
    ]
    print_display_table(rows, columns=["指标", "值"])
    print()
    print("【波动】")
    rows = [
        {"指标": "BOLL(20,2)", "值": f"上轨 {b['upper']:.2f} / 中轨 {b['mid']:.2f} / 下轨 {b['lower']:.2f}"},
        {"指标": "BOLL 带宽", "值": f"{b['bandwidth']:.1f}%" if b["bandwidth"] else "N/A"},
        {"指标": "%B(带内位置)", "值": f"{b['percent_b']:.2f}(0=下轨,0.5=中轨,1=上轨)"},
        {"指标": "ATR(14)", "值": f"{ind['atr14']:.2f}({ind['atr_pct']:.2f}%/日)"},
    ]
    print_display_table(rows, columns=["指标", "值"])
    print()
    print("【量能】")
    ob = ind["obv"]
    rows = [
        {"指标": "OBV", "值": f"{ob['obv']:,.0f}(20期斜率{'↑' if ob['rising_20'] else '↓'})"},
        {"指标": "MFI(14)", "值": f"{ind['mfi14']:.1f}" if ind["mfi14"] is not None else "N/A"},
        {"指标": "量比(5日)", "值": f"{ind['volume_ratio']:.2f}" if ind["volume_ratio"] is not None else "N/A"},
    ]
    print_display_table(rows, columns=["指标", "值"])
    print()
    p52 = ind["position_52w"]
    print("【位置】")
    print(f"  52周区间: {p52['low']:.2f} ~ {p52['high']:.2f},当前位于 {p52['position']:.1f}% 分位")
    print(f"  区间最大回撤: {ind['max_drawdown']*100:.1f}%  累计收益: {ind['total_return_pct']:+.1f}%")
    print()
    print(f"【信号】(共 {len(ind['signals'])} 条)")
    for s in ind["signals"]:
        print(f"  {s}")
    return ind


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="全套技术指标(MA/MACD/RSI/BOLL/KDJ/ATR/OBV等)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 700.HK")
    parser.add_argument("--count", type=int, default=300, help="K 线根数(默认 300,覆盖年线)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        show_indicators(args.symbol, count=args.count, output_json=args.output_json)
    except Exception as e:
        print_error("技术指标", str(e))
        sys.exit(1)
