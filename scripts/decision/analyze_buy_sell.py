"""买卖决策仪表盘(多维度聚合 → 多空对照 + 综合信号)。

旗舰脚本: 把全部模块的判断压缩成一页纸,回答"当下偏买还是偏卖"。
聚合六维(每维失败不致命,跳过并标注):
  ① 技术面(30%): calc_technical_score 综合分
  ② 估值面(15%): 估值历史百分位(便宜=高分)
  ③ 资金面(20%): 主力大单净流入方向 + 沽空压力
  ④ 期权定位(10%): P/C 比率 + IV 贵贱(仅美股,其他市场中性)
  ⑤ 分析师(15%): 评级共识 + 目标价空间
  ⑥ 事件风险(10%): 距下次财报的距离(临近财报降分,防事件风险)

输出:
  - 六维得分表(0-100 归一 + 加权)
  - 多头因素 vs 空头因素 对照清单
  - 综合信号: 看多/偏多/中性/偏空/看空

⚠️ 本工具是数据聚合参考,非投资建议;权重为设计选择。

用法:
    python analyze_buy_sell.py AAPL.US
    python analyze_buy_sell.py 0700.HK --json
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.normpath(os.path.join(_HERE, "..")), _HERE,
           os.path.normpath(os.path.join(_HERE, "..", "technical")),
           os.path.normpath(os.path.join(_HERE, "..", "fundamental")),
           os.path.normpath(os.path.join(_HERE, "..", "quote"))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import (  # noqa: E402
    calc_hv, get_atm_iv, get_capital_flow_snapshot, get_finance_calendar,
    get_kline, get_option_chain, get_option_expirations, get_option_volume_realtime,
    get_short_trades, get_underlying_price, is_empty, print_error, print_json,
    to_float,
)
from calc_technical_score import score as tech_score  # noqa: E402
from get_valuation_percentile import analyze as val_analyze  # noqa: E402
from get_analyst_consensus import analyze as analyst_analyze  # noqa: E402

WEIGHTS = {"技术面": 30, "估值面": 15, "资金面": 20, "期权定位": 10, "分析师": 15, "事件风险": 10}


def _dim_technical(symbol: str, bulls: list, bears: list) -> tuple[float | None, str]:
    try:
        r = tech_score(symbol, quiet=True)
        for s in (r.get("signals") or [])[:4]:
            if s.startswith("🟢"):
                bulls.append(f"技术: {s[2:]}")
            elif s.startswith("🔴"):
                bears.append(f"技术: {s[2:]}")
        return r["technical_score"], r["label"]
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def _dim_valuation(symbol: str, bulls: list, bears: list) -> tuple[float | None, str]:
    try:
        r = val_analyze(symbol, quiet=True)
        main = r.get("main") or {}
        p = main.get("percentile")
        if p is None:
            return None, "无数据"
        # 便宜(低分位)= 高分
        score = 100 - p
        if p < 30:
            bulls.append(f"估值: {main.get('metric')} 处历史 {p:.0f}% 低分位(便宜)")
        elif p > 70:
            bears.append(f"估值: {main.get('metric')} 处历史 {p:.0f}% 高分位(偏贵)")
        return score, f"{main.get('metric')} {main.get('current')}(历史{p:.0f}%分位)"
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def _dim_capital(symbol: str, bulls: list, bears: list) -> tuple[float | None, str]:
    try:
        cap = get_capital_flow_snapshot(symbol)
        net_large = to_float((cap.get("net") or {}).get("large"), 0) or 0
        s = 50.0
        if net_large > 0:
            k = min(abs(net_large) / 3e6, 1.0)
            s = 50 + 50 * k
            bulls.append(f"资金: 主力大单净流入 {abs(net_large)/1e8:.2f}亿")
        elif net_large < 0:
            k = min(abs(net_large) / 3e6, 1.0)
            s = 50 - 50 * k
            bears.append(f"资金: 主力大单净流出 {abs(net_large)/1e8:.2f}亿")
        # 沽空压力
        try:
            st = get_short_trades(symbol, count=10)
            rates = [to_float(r.get("rate")) for r in st.get("data", [])]
            rates = [r for r in rates if r is not None]
            if rates:
                latest = rates[-1]
                if latest >= 0.3:
                    s -= 10
                    bears.append(f"沽空: 最新沽空比率 {latest*100:.0f}%(偏高压制)")
                elif latest <= 0.1:
                    s += 5
                return max(min(s, 100), 0), f"大单净额 {net_large/1e4:.0f}万,沽空率 {latest*100:.0f}%"
        except Exception:
            pass
        return max(min(s, 100), 0), f"大单净额 {net_large/1e4:.0f}万"
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def _dim_options(symbol: str, bulls: list, bears: list) -> tuple[float | None, str]:
    if not symbol.upper().endswith(".US"):
        return 50.0, "非美股,期权维度中性"
    try:
        s = 50.0
        parts = []
        pc = get_option_volume_realtime(symbol).get("pc_ratio")
        if pc is not None:
            parts.append(f"P/C {pc:.2f}")
            if pc > 1.0:
                s -= 15
                bears.append(f"期权: P/C 比率 {pc:.2f}(看跌对冲偏重)")
            elif pc < 0.7:
                s += 10
                bulls.append(f"期权: P/C 比率 {pc:.2f}(偏多)")
        # IV vs HV
        exps = get_option_expirations(symbol)
        if exps:
            chain = get_option_chain(symbol, exps[0])
            price = get_underlying_price(symbol)
            iv = get_atm_iv(chain, price) if price else None
            if iv:
                klines = get_kline(symbol, count=31)
                closes = [k["close"] for k in klines if k.get("close") is not None]
                hv = calc_hv(closes)
                if hv:
                    parts.append(f"IV/HV {iv/hv:.2f}")
                    if iv / hv > 1.3:
                        s += 5  # IV 贵 → 卖方占优,对持有正股者偏中性偏正(收租机会)
                        bulls.append(f"期权: IV 偏贵(IV/HV {iv/hv:.2f},卖权收租机会)")
                    elif iv / hv < 0.8:
                        s -= 5
        return max(min(s, 100), 0), ", ".join(parts) or "无数据"
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def _dim_analyst(symbol: str, bulls: list, bears: list) -> tuple[float | None, str]:
    try:
        r = analyst_analyze(symbol, quiet=True)
        rat = r.get("rating") or {}
        total = to_float(rat.get("total"), 0) or 0
        if total <= 0:
            return None, "无评级覆盖"
        bull = ((to_float(rat.get("buy"), 0) or 0) + (to_float(rat.get("over"), 0) or 0))
        bear = ((to_float(rat.get("sell"), 0) or 0) + (to_float(rat.get("under"), 0) or 0))
        s = 50 + (bull - bear) / total * 50
        if bull / total >= 0.6:
            bulls.append(f"分析师: {rat.get('label')}({bull}/{int(total)} 家看多)")
        if bear / total >= 0.3:
            bears.append(f"分析师: {bear}/{int(total)} 家看空")
        t = r.get("target_price") or {}
        up = t.get("upside_to_mid_pct")
        if up is not None:
            if up > 15:
                s = min(s + 10, 100)
                bulls.append(f"目标价: 距中值还有 {up:+.1f}% 空间")
            elif up < -10:
                s = max(s - 10, 0)
                bears.append(f"目标价: 现价已高于中值目标 {abs(up):.1f}%")
        return max(min(s, 100), 0), f"{rat.get('label')},目标中值空间 {up:+.1f}%" if up is not None else str(rat.get("label"))
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def _dim_event(symbol: str, bulls: list, bears: list) -> tuple[float | None, str]:
    try:
        market = symbol.rsplit(".", 1)[-1] if "." in symbol else "US"
        buckets = get_finance_calendar(category="report", market=market, symbol=symbol, count=20)
        today = datetime.now().strftime("%Y-%m-%d")
        for b in buckets:
            for info in b.get("infos", []):
                d = str(info.get("date", "")).replace(".", "-")[:10]
                try:
                    days = (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days
                except ValueError:
                    continue
                if days >= 0:
                    if days <= 7:
                        bears.append(f"事件: {days} 天后发财报(波动风险)")
                        return 30.0, f"{days} 天后财报"
                    return 90.0, f"下次财报还有 {days} 天"
        return 70.0, "日历中无近期财报"
    except Exception as e:
        return None, f"数据失败({str(e)[:30]})"


def analyze(symbol: str, output_json: bool = False) -> dict:
    price = get_underlying_price(symbol)
    bulls: list[str] = []
    bears: list[str] = []

    dims = {
        "技术面": _dim_technical(symbol, bulls, bears),
        "估值面": _dim_valuation(symbol, bulls, bears),
        "资金面": _dim_capital(symbol, bulls, bears),
        "期权定位": _dim_options(symbol, bulls, bears),
        "分析师": _dim_analyst(symbol, bulls, bears),
        "事件风险": _dim_event(symbol, bulls, bears),
    }

    total_w = 0.0
    acc = 0.0
    dim_out = {}
    for name, (score_v, note) in dims.items():
        if score_v is None:
            dim_out[name] = {"score": None, "weight": WEIGHTS[name], "detail": note}
            continue
        acc += score_v * WEIGHTS[name]
        total_w += WEIGHTS[name]
        dim_out[name] = {"score": round(score_v, 1), "weight": WEIGHTS[name], "detail": note}
    composite = round(acc / total_w, 1) if total_w else None

    if composite is None:
        signal = "数据不足"
    elif composite >= 70:
        signal = "🟢🟢 看多"
    elif composite >= 55:
        signal = "🟢 偏多"
    elif composite > 45:
        signal = "⚪ 中性"
    elif composite > 30:
        signal = "🔴 偏空"
    else:
        signal = "🔴🔴 看空"

    result = {
        "symbol": symbol,
        "price": price,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dimensions": dim_out,
        "composite_score": composite,
        "signal": signal,
        "bull_factors": bulls,
        "bear_factors": bears,
        "disclaimer": "数据聚合参考,非投资建议。权重为设计选择,请结合自身判断。",
    }

    if output_json:
        print_json(result)
        return result

    print(f"{'='*56}")
    print(f"  {symbol} 买卖决策仪表盘  现价 {price}  {result['generated_at']}")
    print(f"{'='*56}")
    print(f"\n  综合信号: {signal}  (综合分 {composite}/100)\n")
    print("六维评分:")
    for name, d in dim_out.items():
        sc = f"{d['score']:.0f}/100" if d["score"] is not None else "N/A"
        print(f"  [{name}](权重{d['weight']}%) {sc} — {d['detail']}")
    print(f"\n  多头因素({len(bulls)}):")
    for b in bulls or ["(无)"]:
        print(f"    🟢 {b}")
    print(f"  空头因素({len(bears)}):")
    for b in bears or ["(无)"]:
        print(f"    🔴 {b}")
    print(f"\n  ⚠️ {result['disclaimer']}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="买卖决策仪表盘(六维聚合)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 0700.HK")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, output_json=args.output_json)
    except Exception as e:
        print_error("买卖仪表盘", str(e))
        sys.exit(1)
