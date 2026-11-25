"""IV Rank(隐含波动率排名,B 档·基于本地累积序列 + 1年滚动HV冷启动过渡)。

对应 Futu: get_option_underlying_overview(IV_RANK 字段)

⚠️ Longbridge 不直接提供历史 IV / IV Rank。本脚本依赖 get_iv_history 的本地累积序列:
   - 本地可比恒定30日 IV ≥ min_points(默认 20)时:直接计算真实 IV Rank。
   - 样本 < min_points(含首次 1 天冷启动)且未传 --strict 时:基于过去 1 年正股日线滚动
     30 日实现波动率 HV30 序列提供过渡分位参考(rank_basis="hv_52w_proxy"，iv_rank 保持 None)。

IV Rank = (当前IV - 最低IV) / (最高IV - 最低IV) × 100

用法:
    python calc_iv_rank.py AAPL.US
    python calc_iv_rank.py AAPL.US --json
    python calc_iv_rank.py AAPL.US --min-points 20 --strict  # 样本不足时硬报错
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_kline_adjusted,
    print_error,
    print_json,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from get_iv_history import (  # noqa: E402
    calc_hv_proxy_metrics,
    check_series_continuity,
    comparable_iv_series,
    iv_history as _build_series,
)


def calc_iv_rank(
    symbol: str,
    min_points: int = 20,
    output_json: bool = False,
    allow_proxy: bool = True,
) -> dict:
    hist = _build_series(symbol, append=True, output_json=False, quiet=True)
    if not hist.get("appended_today", False):
        raise ValueError("无法采集当前恒定30日 IV，历史样本保留")
    if min_points < 2:
        raise ValueError("至少需要两个可比 IV 样本")
    series = comparable_iv_series(hist.get("series", []))
    observation = hist.get("observed_at")
    observed_day = observation[:10] if observation else None
    if observed_day:
        series = [row for row in series if row["date"] <= observed_day]
        if not series or series[-1]["date"] != observed_day:
            raise ValueError("当前观测日没有有效的恒定30日 IV 样本")

    coverage_warning = check_series_continuity(series, observed_day=observed_day, min_points=min_points)

    if len(series) < min_points:
        if not allow_proxy or not series:
            raise ValueError(
                f"历史 IV 数据不足(仅 {len(series)} 点,需 ≥ {min_points})。"
                f"请多运行 get_iv_history.py 积累数据。当前已记录: "
                f"{hist.get('date_range', '无')}"
            )
        current = series[-1]["atm_iv_pct"]
        hv_proxy = calc_hv_proxy_metrics(symbol, current, kline_fn=get_kline_adjusted)
        if hv_proxy is None:
            raise ValueError(
                f"历史 IV 数据不足(仅 {len(series)} 点,需 ≥ {min_points})，"
                "且正股 K 线不足以构建 1 年滚动 HV30 代理序列"
            )
        proxy_rank = hv_proxy["hv_proxy_rank"]
        interp = (
            f"相对过去1年HV30偏高(分位 {proxy_rank}%，VRP {hv_proxy['vrp_pct']:+.2f}%)"
            if proxy_rank > 70 else
            f"相对过去1年HV30偏低(分位 {proxy_rank}%，VRP {hv_proxy['vrp_pct']:+.2f}%)"
            if proxy_rank < 30 else
            f"相对过去1年HV30适中(分位 {proxy_rank}%，VRP {hv_proxy['vrp_pct']:+.2f}%)"
        )
        result = {
            "symbol": symbol,
            "current_iv_pct": current,
            "observed_at": series[-1].get("observed_at"),
            "quote_freshness": "unknown",
            "iv_rank": None,
            "rank_basis": "hv_52w_proxy",
            "hv_proxy_rank": proxy_rank,
            "hv_proxy": hv_proxy,
            "data_points": len(series),
            "min_points": min_points,
            "date_range": f"{series[0]['date']} ~ {series[-1]['date']}",
            "iv_high_pct": None,
            "iv_low_pct": None,
            "coverage_warning": coverage_warning,
            "interpretation": interp,
            "method": "当前30日ATM IV 落在过去1年(252交易日)滚动HV30区间中的分位(冷启动代理)",
            "note": (
                f"冷启动过渡模式: 本地可比 IV 仅 {len(series)}/{min_points} 点，"
                "使用过去1年滚动30日 HV 序列作为参考基准；积累满 20 天后自动切换为真实 IV Rank。"
            ),
        }
        if output_json:
            print_json(result)
            return result

        print(f"{symbol} IV Rank [冷启动 1 年 HV30 过渡参考](本地已采 {len(series)}/{min_points} 点)")
        if result["observed_at"]:
            print(f"  观测时间:     {result['observed_at']}，行情新鲜度未知")
        print(f"  当前30日 IV:  {current}%  (真 IV Rank: 暂缺,需再采 {min_points - len(series)} 天)")
        print(f"  当前 HV(30D): {hv_proxy['hv_current_pct']}%  |  VRP(IV-HV): {hv_proxy['vrp_pct']:+.2f}%")
        print(f"  1年 HV30区间: {hv_proxy['hv_low_pct']}% ~ {hv_proxy['hv_high_pct']}% (中位 {hv_proxy['hv_median_pct']}%)")
        print(f"  HV代理 Rank:  {proxy_rank}  → {interp}")
        if hv_proxy.get("above_hv_52w_high"):
            print("  ⚠️ 当前 IV 已高于过去 1 年所有已实现波动率峰值(计入显著事件/恐慌溢价)")
        elif hv_proxy.get("below_hv_52w_low"):
            print("  ⚠️ 当前 IV 低于过去 1 年所有已实现波动率低谷")
        if coverage_warning:
            print(f"  ⚠️ 连续性提示: {coverage_warning}")
        return result

    ivs = [s["atm_iv_pct"] for s in series]
    current = ivs[-1]
    hi, lo = max(ivs), min(ivs)
    rank = ((current - lo) / (hi - lo) * 100) if hi > lo else 50.0
    hv_proxy = None
    if coverage_warning:
        try:
            hv_proxy = calc_hv_proxy_metrics(symbol, current, kline_fn=get_kline_adjusted)
        except Exception:
            hv_proxy = None

    result = {
        "symbol": symbol,
        "current_iv_pct": current,
        "observed_at": series[-1].get("observed_at"),
        "quote_freshness": "unknown",
        "iv_rank": round(rank, 1),
        "rank_basis": "iv_history",
        "data_points": len(series),
        "min_points": min_points,
        "date_range": f"{series[0]['date']} ~ {series[-1]['date']}",
        "iv_high_pct": hi,
        "iv_low_pct": lo,
        "coverage_warning": coverage_warning,
        "interpretation": (
            "高位(>70): 接近样本上沿"
            if rank > 70 else
            "低位(<30): 接近样本下沿"
            if rank < 30 else
            "中位(30-70): IV 适中"
        ),
        "method": "(当前IV - 最低IV) / (最高IV - 最低IV) × 100",
        "note": "Longbridge 不直接提供 IV Rank,使用全部本地恒定30日样本，窗口随本地记录变化。观测时间为采集时间，行情新鲜度未知",
    }
    if hv_proxy is not None:
        result["hv_proxy"] = hv_proxy

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} IV Rank(本地累积 {len(series)} 点,{hist['date_range']})")
    if result["observed_at"]:
        print(f"  观测时间: {result['observed_at']}，行情新鲜度未知")
    print(f"  当前 IV:   {current}%")
    print(f"  区间 IV:   {lo}% ~ {hi}%")
    print(f"  IV Rank:   {result['iv_rank']}  → {result['interpretation']}")
    if coverage_warning:
        print(f"  ⚠️ 连续性提示: {coverage_warning}")
        if hv_proxy is not None:
            print(f"  ↳ 交叉参考(1年HV30代理): Rank {hv_proxy['hv_proxy_rank']}, VRP {hv_proxy['vrp_pct']:+.2f}%")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IV Rank(基于本地累积 IV 序列)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--min-points", type=int, default=20, help="最少数据点数(默认 20)")
    parser.add_argument("--strict", action="store_true", help="样本不足时不启用 1 年 HV 过渡参考，直接报错")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        calc_iv_rank(
            args.symbol,
            min_points=args.min_points,
            output_json=args.output_json,
            allow_proxy=not args.strict,
        )
    except Exception as e:
        print_error("IV Rank", str(e))
        sys.exit(1)
