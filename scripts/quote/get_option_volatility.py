"""期权波动率分析:HV vs IV 对比(B 档·计算)。

对应 Futu: get_option_volatility
- Futu: 服务端直接返回 IV/HV/波动率溢价
- Longbridge: IV 取自 chain(call_iv/put_iv),HV 用 K 线收盘价自算

⚠️ HV 为本地计算值,与 Futu 服务端 HV 可能有细微差异(数据源/算法不同)。

用法:
    # 指定到期日(从 chain 取 ATM IV)
    python get_option_volatility.py AAPL.US --expiry 2026-09-18
    # 自动用最近到期日
    python get_option_volatility.py AAPL.US
    python get_option_volatility.py AAPL.US --hv-days 30 --json
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    calc_hv,
    get_atm_iv,
    get_kline,
    get_option_chain,
    get_option_expirations,
    get_underlying_price,
    print_error,
    print_json,
)


def analyze(
    symbol: str,
    expiry: str | None = None,
    hv_days: int = 30,
    option_type: str = "CALL",
    output_json: bool = False,
) -> dict:
    # 1. 确定到期日
    if expiry is None:
        expirations = get_option_expirations(symbol)
        if not expirations:
            raise ValueError(f"{symbol} 无可用到期日(可能不支持期权或非美股)")
        expiry = expirations[0]

    # 2. 取正股现价
    price = get_underlying_price(symbol)
    if price is None:
        raise ValueError(f"无法获取 {symbol} 现价")

    # 3. 从 chain 取 ATM IV(小数形式)
    chain = get_option_chain(symbol, expiry)
    iv = get_atm_iv(chain, price, option_type)
    if iv is None:
        raise ValueError(f"{expiry} 的 chain 中找不到 ATM IV")

    # 4. 用 K 线算 HV(年化)
    klines = get_kline(symbol, count=hv_days + 1)
    closes = [k["close"] for k in klines if k.get("close") is not None]
    hv = calc_hv(closes)

    # 5. IV/HV 对比
    iv_hv_ratio = (iv / hv) if (iv and hv and hv > 0) else None

    result = {
        "symbol": symbol,
        "expiry": expiry,
        "underlying_price": price,
        "option_type": option_type,
        "implied_volatility": iv,           # 小数,如 0.234
        "iv_pct": round(iv * 100, 2),       # 百分比,如 23.4
        "historical_volatility": hv,        # 小数
        "hv_pct": round(hv * 100, 2) if hv else None,
        "hv_days": hv_days,
        "iv_hv_ratio": round(iv_hv_ratio, 3) if iv_hv_ratio else None,
        "note": "HV 为本地计算值(对数收益年化),非服务端返回",
    }

    # 贵贱判断
    if iv_hv_ratio:
        if iv_hv_ratio > 1.3:
            result["valuation"] = "IV 偏贵(期权定价高于近期波动)"
        elif iv_hv_ratio < 0.8:
            result["valuation"] = "IV 偏便宜(期权定价低于近期波动)"
        else:
            result["valuation"] = "IV 与 HV 接近(合理区间)"

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 期权波动率分析(到期 {expiry},HV 窗口 {hv_days} 日)")
    print(f"  正股现价:     {price}")
    print(f"  ATM IV({option_type}):  {result['iv_pct']}%")
    print(f"  HV({hv_days}日年化):    {result['hv_pct']}%")
    print(f"  IV/HV 比率:   {result['iv_hv_ratio']}")
    print(f"  判断:         {result['valuation']}")
    print(f"  注: HV 为本地计算值,与 Futu 服务端 HV 可能有细微差异")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="期权波动率分析(IV vs HV)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--expiry", default=None, help="到期日 YYYY-MM-DD(默认最近)")
    parser.add_argument("--hv-days", type=int, default=30, help="HV 计算窗口(默认 30 日)")
    parser.add_argument("--type", default="CALL", help="ATM IV 取 Call 还是 Put(默认 CALL)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, expiry=args.expiry, hv_days=args.hv_days,
                option_type=args.type, output_json=args.output_json)
    except Exception as e:
        print_error("期权波动率分析", str(e))
        sys.exit(1)
