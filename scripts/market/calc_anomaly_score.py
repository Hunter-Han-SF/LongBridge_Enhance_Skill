"""单标的异动综合打分(融合多数据源)。

跨模块旗舰脚本: 综合异动信号、资金流方向、涨跌幅偏离、成交量比,
给单标的一个 0-100 的异动强度分 + 方向判断 + 原因解读。

打分维度(各占权重):
  1. 异动信号数(40%): 来自 anomaly,该标的有几条异动 + 情绪方向
  2. 资金流方向(30%): 来自 capital flow,大单净流入/流出
  3. 涨跌幅偏离(20%): 来自 quote,相对前日的涨跌幅
  4. 成交量比(10%): 来自 top_movers 或 quote,是否放量

输出:
  - 综合分(0-100,越高越异动)
  - 方向(利多/利空/中性)
  - 各维度明细
  - 主要原因解读

用法:
    python calc_anomaly_score.py AAPL.US
    python calc_anomaly_score.py 700.HK --market HK
    python calc_anomaly_score.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    counter_id_to_symbol,
    get_anomaly,
    get_capital_flow_snapshot,
    get_top_movers,
    is_empty,
    print_error,
    print_json,
    run_cli,
    to_float,
)


def _get_quote(symbol: str) -> dict:
    """获取实时报价。"""
    data = run_cli("quote", symbol)
    if is_empty(data) or not isinstance(data, list) or not data:
        return {}
    q = data[0] if isinstance(data[0], dict) else {}
    # ⚠️ 字段名以实测为准:涨跌幅是 change_percentage(小数形式,0.29=0.29%)
    return {
        "last": to_float(q.get("last")),
        "change_pct": to_float(q.get("change_percentage")),
        "volume": to_float(q.get("volume")),
    }


def _score_dimension(symbol: str, market: str) -> dict:
    """计算各维度得分。返回 {dim: {score, detail}}。"""
    dims = {}

    # 维度1: 异动信号数(0-40 分)
    try:
        anomaly = get_anomaly(market=market, symbol=symbol, count=100)
        changes = anomaly["changes"]
        bull = sum(1 for c in changes if to_float(c.get("emotion")) == 1)
        bear = sum(1 for c in changes if to_float(c.get("emotion")) == 2)
        signal_count = len(changes)
        # 信号数越多分越高,上限 40
        sig_score = min(signal_count * 8, 40)
        net_dir = bull - bear
        dims["anomaly"] = {
            "score": sig_score,
            "weight": 0.4,
            "signals": signal_count,
            "bull": bull,
            "bear": bear,
            "direction": "利多" if net_dir > 0 else ("利空" if net_dir < 0 else "中性"),
            "types": list({c.get("alert_name", "") for c in changes})[:5],
        }
    except Exception as e:
        dims["anomaly"] = {"score": 0, "weight": 0.4, "error": str(e)}

    # 维度2: 资金流方向(0-30 分)
    try:
        cap = get_capital_flow_snapshot(symbol)
        net = cap.get("net", {}) if cap else {}
        net_large = to_float(net.get("large"), 0) or 0
        net_total = to_float(net.get("total"), 0) or 0
        # 净流入越大分越高(绝对值归一化到 30)。
        # 单位为当地货币完整元(common 已把 CLI 的"万"×1e4 换算),
        # 大单净流入约 300 万(美元/港元)计满 30 分
        cap_score = min(abs(net_large) / 1e5, 30) if net_large != 0 else 0
        dims["capital"] = {
            "score": round(cap_score, 1),
            "weight": 0.3,
            "net_large": net_large,
            "net_total": net_total,
            "direction": "主力流入" if net_large > 0 else ("主力流出" if net_large < 0 else "持平"),
        }
    except Exception as e:
        dims["capital"] = {"score": 0, "weight": 0.3, "error": str(e)}

    # 维度3: 涨跌幅偏离(0-20 分)
    try:
        q = _get_quote(symbol)
        chg = to_float(q.get("change_pct"))
        # ⚠️ CLI 的 change_percentage 是百分比形式(0.29 = 0.29%),不是小数
        # 涨跌幅绝对值越大分越高:超过 ±3% 开始计分,±8% 满分
        chg_score = min(max((abs(chg) - 3) / 5, 0) * 20, 20) if chg is not None else 0
        dims["change"] = {
            "score": round(chg_score, 1),
            "weight": 0.2,
            "change_pct": chg,
            "price": q.get("last"),
            "direction": "上涨" if chg and chg > 0 else ("下跌" if chg and chg < 0 else "持平"),
        }
    except Exception as e:
        dims["change"] = {"score": 0, "weight": 0.2, "error": str(e)}

    # 维度4: 是否在异动榜(0-10 分)
    try:
        tm = get_top_movers(market=market, sort="change", count=100)
        in_movers = False
        mover_reason = ""
        for ev in tm["events"]:
            stock = ev.get("stock") or {}
            if stock.get("symbol") == symbol:
                in_movers = True
                mover_reason = ev.get("alert_reason", "")
                break
        dims["top_movers"] = {
            "score": 10 if in_movers else 0,
            "weight": 0.1,
            "in_movers": in_movers,
            "reason": mover_reason,
        }
    except Exception as e:
        dims["top_movers"] = {"score": 0, "weight": 0.1, "error": str(e)}

    return dims


def calc_score(symbol: str, market: str = "US", output_json: bool = False) -> dict:
    dims = _score_dimension(symbol, market)

    # 加权综合分
    total = sum(d.get("score", 0) * d.get("weight", 0) for d in dims.values())
    total = round(total, 1)

    # 方向综合(各维度方向投票)
    directions = []
    for d in dims.values():
        direction = d.get("direction")
        if direction:
            directions.append(direction)
    bull_votes = sum(1 for d in directions if d in ("利多", "主力流入", "上涨"))
    bear_votes = sum(1 for d in directions if d in ("利空", "主力流出", "下跌"))
    if bull_votes > bear_votes:
        overall_dir = "利多 🟢"
    elif bear_votes > bull_votes:
        overall_dir = "利空 🔴"
    else:
        overall_dir = "中性 ⚪"

    # 强度标签
    if total >= 60:
        intensity = "🔥 强异动"
    elif total >= 35:
        intensity = "⚡ 中等异动"
    elif total >= 15:
        intensity = "轻微异动"
    else:
        intensity = "无明显异动"

    result = {
        "symbol": symbol,
        "market": market,
        "anomaly_score": total,
        "intensity": intensity,
        "direction": overall_dir,
        "dimensions": dims,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 异动综合打分")
    print(f"  📊 综合分: {total}/100  {intensity}")
    print(f"  🧭 方向: {overall_dir}")
    print()
    print("维度明细:")
    label_map = {"anomaly": "异动信号", "capital": "资金流", "change": "涨跌幅", "top_movers": "异动榜"}
    for key, d in dims.items():
        label = label_map.get(key, key)
        weighted = round(d.get("score", 0) * d.get("weight", 0), 1)
        if "error" in d:
            print(f"  [{label}] ✗ 数据获取失败({d['error'][:30]})")
            continue
        print(f"  [{label}] 得分 {d.get('score',0)}/{int(d.get('weight',0)*100)} "
              f"(加权 {weighted}) — {d.get('direction', d.get('in_movers', ''))}")
        if key == "anomaly" and d.get("types"):
            print(f"    信号类型: {', '.join(d['types'])}")
        if key == "top_movers" and d.get("reason"):
            print(f"    榜单原因: {d['reason']}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="单标的异动综合打分(融合多数据源)")
    parser.add_argument("symbol", help="标的代码,如 AAPL.US / 700.HK")
    parser.add_argument("--market", default=None, help="市场 HK|US|CN|SG(默认从 symbol 推断)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    market = args.market or (args.symbol.rsplit(".", 1)[-1].upper() if "." in args.symbol else "US")
    if market in ("SH", "SZ"):
        market = "CN"
    try:
        calc_score(args.symbol, market=market, output_json=args.output_json)
    except Exception as e:
        print_error("异动综合打分", str(e))
        sys.exit(1)
