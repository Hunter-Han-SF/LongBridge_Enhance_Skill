"""计算 Gamma Exposure (GEX) 和 Gamma 翻转点。

⚠️ 重要限制:同 get_put_call_wall,Longbridge chain 不返回按行权价的 OI,
   本脚本用成交量(call_vol/put_vol)加权,是真实 GEX 的近似。

GEX 含义:
  - Gamma 衡量 delta 对标的价格变化的敏感度
  - GEX = Σ(gamma × OI × 100 × spot² × 0.01),按 call(+)/put(-) 加权
    (做市商卖 Put 时做多 delta 对冲,符号为正;约定因数据源而异,这里用通用约定)
  - 正 GEX 区域:做市商对冲方向抑制波动(价格涨就卖,跌就买)→ 低波动
  - 负 GEX 区域:做市商对冲方向放大波动(价格涨就买,跌就卖)→ 高波动(易出现逼空/闪崩)
  - Gamma 翻转点(Zero Gamma Level): GEX 由正转负的价位,市场稳定性临界点

计算方法:
  对每个行权价 K:
    call_gex = gamma_call × vol_call × 100 × S² × 0.01
    put_gex  = gamma_put  × vol_put  × 100 × S² × 0.01 × (-1)  (put 对冲方向相反)
  net_gex(K) = call_gex + put_gex
  总 GEX = Σ net_gex(K)
  翻转点 = 累积 GEX 跨越零的价位(这里用各 strike 的 net_gex 符号变化定位)

用法:
    python calc_gex.py AAPL.US --date 2026-09-18
    python calc_gex.py AAPL.US --date 2026-09-18 --rate 0.045
    python calc_gex.py AAPL.US --date 2026-09-18 --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    bs_greeks,
    days_to_years,
    get_option_chain,
    get_underlying_price,
    is_empty,
    print_display_table,
    print_error,
    print_json,
    to_float,
)


def calc_gex(
    symbol: str,
    date: str,
    rate: float = 0.045,
    output_json: bool = False,
) -> dict:
    price = get_underlying_price(symbol)
    if not price:
        raise ValueError(f"无法获取 {symbol} 现价")
    chain = get_option_chain(symbol, date)
    if is_empty(chain):
        raise ValueError(f"{symbol} 在 {date} 无期权链数据")

    T = days_to_years(date)
    if T <= 0:
        raise ValueError(f"到期日 {date} 已过期或为今天,GEX 计算无意义")

    # 逐 strike 算 gamma 加权
    rows = []
    total_gex = 0.0
    for r in chain:
        strike = to_float(r.get("strike"))
        if strike is None or strike <= 0:
            continue
        call_iv = to_float(r.get("call_iv"))
        put_iv = to_float(r.get("put_iv"))
        call_vol = to_float(r.get("call_vol"), 0) or 0
        put_vol = to_float(r.get("put_vol"), 0) or 0
        if call_vol == 0 and put_vol == 0:
            continue

        # call gamma
        call_gamma = bs_greeks(price, strike, T, rate, call_iv, "C")["gamma"] if call_iv and call_iv > 0 else 0
        # put gamma(BS 下 call/put gamma 相同,但 IV 可能不同,分别算)
        put_gamma = bs_greeks(price, strike, T, rate, put_iv, "P")["gamma"] if put_iv and put_iv > 0 else 0

        # GEX 约定:每张合约 100 股,gamma exposure per 1% move
        # call_gex = gamma × vol × 100 × S² × 0.01(做市商通常卖 call → 负,但此处用买方视角)
        # 采用通用约定:call 贡献正,put 贡献负(做市商对冲方向)
        call_gex = call_gamma * call_vol * 100 * price * price * 0.01
        put_gex = -put_gamma * put_vol * 100 * price * price * 0.01
        net = call_gex + put_gex
        total_gex += net

        rows.append({
            "strike": strike,
            "call_gamma": round(call_gamma, 6),
            "put_gamma": round(put_gamma, 6),
            "call_vol": call_vol,
            "put_vol": put_vol,
            "call_gex": round(call_gex, 0),
            "put_gex": round(put_gex, 0),
            "net_gex": round(net, 0),
        })

    # 按 strike 排序,找翻转点(net_gex 累积跨越零的区间)
    rows.sort(key=lambda x: x["strike"])
    zero_gamma = _find_zero_gamma(rows, price)

    result = {
        "symbol": symbol,
        "expiry": date,
        "underlying_price": price,
        "rate": rate,
        "T_years": round(T, 4),
        "total_gex": round(total_gex, 0),
        "total_gex_label": _gex_label(total_gex),
        "zero_gamma_level": zero_gamma,
        "strikes_analyzed": len(rows),
        "note": "基于成交量加权(非真实 OI)。Longbridge chain 不返回按行权价的 OI,"
                "GEX 数值为近似,主要看相对大小和翻转点位置。",
        "per_strike": rows,
    }

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} Gamma Exposure 分析(到期 {date},现价 {price})")
    print(f"  ⚠️ 基于成交量近似(非真实 OI)")
    print(f"  剩余时间: {T*365:.0f} 天")
    print(f"  总 GEX: {total_gex:,.0f}  → {_gex_label(total_gex)}")
    print(f"  Gamma 翻转点: {zero_gamma if zero_gamma else '未检测到明确翻转'}")
    print()
    # 按 |net_gex| 排序,显示贡献最大的 strike
    top = sorted(rows, key=lambda x: abs(x["net_gex"]), reverse=True)[:8]
    top.sort(key=lambda x: x["strike"])
    print("Gamma 贡献最大的行权价(top 8 by |net_gex|):")
    print_display_table(
        [{"行权价": r["strike"], "call_γ": r["call_gamma"], "put_γ": r["put_gamma"],
          "call_vol": r["call_vol"], "put_vol": r["put_vol"],
          "net_GEX": f"{r['net_gex']:,.0f}"} for r in top],
        columns=["行权价", "call_γ", "put_γ", "call_vol", "put_vol", "net_GEX"])
    return result


def _gex_label(total_gex: float) -> str:
    """总 GEX 解读。"""
    if total_gex > 0:
        return "正 GEX(做市商抑制波动,市场偏稳)"
    if total_gex < 0:
        return "负 GEX(做市商放大波动,易出现剧烈行情)"
    return "中性"


def _find_zero_gamma(rows: list[dict], spot: float) -> float | None:
    """找累积 GEX 跨越零的价位(简化:找 net_gex 符号变化最显著的 strike 附近)。

    严格做法需要逐 strike 累积并插值,这里用 net_gex 最接近 0 的 strike 近似翻转点。
    """
    if not rows:
        return None
    # 找 net_gex 绝对值最小且接近现价的 strike
    near_spot = [r for r in rows if abs(r["strike"] - spot) / spot < 0.3]
    candidates = near_spot or rows
    closest = min(candidates, key=lambda x: abs(x["net_gex"]))
    return closest["strike"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gamma Exposure (GEX) 分析")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--date", required=True, help="到期日 YYYY-MM-DD")
    parser.add_argument("--rate", type=float, default=0.045, help="无风险利率(默认 0.045)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        calc_gex(args.symbol, args.date, rate=args.rate, output_json=args.output_json)
    except Exception as e:
        print_error("GEX 分析", str(e))
        sys.exit(1)
