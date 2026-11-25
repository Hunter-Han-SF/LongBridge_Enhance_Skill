"""期权波动率分析:HV vs IV 对比(B 档·计算)。

对应 Futu: get_option_volatility
- Futu: 服务端直接返回 IV/HV/波动率溢价
- Longbridge: IV 取自 chain(call_iv/put_iv),HV 用 K 线收盘价自算

⚠️ HV 为本地计算值,与 Futu 服务端 HV 可能有细微差异(数据源/算法不同)。
⚠️ 期限对齐: IV 与 HV 必须覆盖相近的时间窗口。默认取剩余期限最接近 HV 窗口的
   到期日(30 个交易日收益 ≈ 43.5 个自然日),不再取最近到期日——最近到期日可能
   只剩 1~2 天,拿它比 30 日 HV 会系统性误判贵贱。

用法:
    # 指定到期日(从 chain 取 ATM IV;HV 窗口自动对齐该到期日)
    python get_option_volatility.py AAPL.US --expiry 2026-09-18
    # 自动取期限最接近 HV 窗口的到期日
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
    days_to_years,
    get_atm_iv,
    get_kline_adjusted,
    get_option_chain,
    get_option_expirations,
    get_underlying_price,
    get_underlying_price_info,
    price_source_note,
    rank_tenor_expiries,
    regular_session_price,
    print_error,
    print_json,
)


TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365
DEFAULT_HV_DAYS = 30


def analyze(
    symbol: str,
    expiry: str | None = None,
    hv_days: int | None = None,
    option_type: str = "CALL",
    output_json: bool = False,
) -> dict:
    """IV 与 HV 的期限必须对齐,否则贵贱判断没有意义。

    - 不指定到期日(默认): IV 取剩余期限最接近 HV 窗口的到期日。hv_days 个交易日
      收益约覆盖 hv_days × 365/252 个自然日(30 日 ≈ 43.5 天),而最近到期日可能
      只剩 1~2 天(实测 AAPL: 1.28 天 IV 32.8% → 1.36 "偏贵";期限接近的
      24 天到期日 IV 25.7% → 1.06 "合理")。
    - 指定到期日而未指定 --hv-days: HV 窗口自动取该到期日的自然日长度。
    - 两者都指定: 按给定的算,期限相差过大时在 tenor_warning 里提示。
    """
    if hv_days is not None and hv_days < 2:
        raise ValueError("hv-days 至少为 2(需要两个收盘价才能算收益)")

    # 1. 取正股现价(选 ATM 时用常规时段价以与 chain IV 对齐)
    price = get_underlying_price(symbol)
    if price is None:
        raise ValueError(f"无法获取 {symbol} 现价")
    atm_ref = regular_session_price(symbol, price) or price

    # 2. 确定到期日并从 chain 取 ATM IV(若最近期限新链尚无 IV 则依次回退到有有效 IV 的最近期限链)
    iv = None
    if expiry is None:
        expirations = get_option_expirations(symbol)
        if not expirations:
            raise ValueError(f"{symbol} 无可用到期日(可能不支持期权或非美股)")
        target_win = DEFAULT_HV_DAYS if hv_days is None else hv_days
        ranked = rank_tenor_expiries(expirations, target_win * CALENDAR_DAYS_PER_YEAR / TRADING_DAYS_PER_YEAR)
        for cand in ranked:
            chain = get_option_chain(symbol, cand)
            cand_iv = get_atm_iv(chain, atm_ref, option_type)
            if cand_iv is not None and cand_iv > 0:
                expiry = cand
                iv = cand_iv
                break
        if iv is None:
            raise ValueError(f"{symbol} 可用到期日的 chain 中均找不到有效 ATM IV")
    else:
        chain = get_option_chain(symbol, expiry)
        iv = get_atm_iv(chain, atm_ref, option_type)
        if iv is None or iv <= 0:
            raise ValueError(f"{expiry} 的 chain 中找不到 ATM IV(可能刚挂牌尚无成交)")

    iv_days = days_to_years(expiry) * 365
    if hv_days is None:
        window = max(2, round(iv_days * TRADING_DAYS_PER_YEAR / CALENDAR_DAYS_PER_YEAR))
    else:
        window = hv_days
    hv_calendar_days = window * CALENDAR_DAYS_PER_YEAR / TRADING_DAYS_PER_YEAR

    # 3. 用前复权 K 线算 HV(年化);窗口与所选到期日的期限对齐
    klines = get_kline_adjusted(symbol, count=window + 1)
    closes = [k["close"] for k in klines if k.get("close") is not None]
    hv = calc_hv(closes)

    # 4. IV/HV 对比
    iv_hv_ratio = (iv / hv) if (iv and hv and hv > 0) else None
    # 期限相差超过 HV 窗口的四分之一时,比率不再可比(事件溢价落在其中一个窗口内时偏差最大)
    tenor_warning = (None if abs(iv_days - hv_calendar_days) <= 0.25 * hv_calendar_days else
                     f"期限不对齐: IV 剩余 {iv_days:.0f} 个自然日, HV 窗口约 {hv_calendar_days:.0f} 个自然日,"
                     f" 贵贱判断仅供参考")

    result = {
        "symbol": symbol,
        "expiry": expiry,
        "iv_days": round(iv_days, 1),
        "underlying_price": price,
        "atm_reference_price": atm_ref,
        "underlying_price_source": get_underlying_price_info(symbol),
        "option_type": option_type,
        "implied_volatility": iv,           # 小数,如 0.234
        "iv_pct": round(iv * 100, 2),       # 百分比,如 23.4
        "historical_volatility": hv,        # 小数
        "hv_pct": round(hv * 100, 2) if hv else None,
        "hv_days": window,
        "iv_hv_ratio": round(iv_hv_ratio, 3) if iv_hv_ratio else None,
        "tenor_warning": tenor_warning,
        "valuation": None,                  # HV 算不出时保持 None(下方判断跳过)
        "note": "HV 为基于前复权 K 线的本地计算值(对数收益年化),非服务端返回。IV 取有有效报价且期限最接近 HV 窗口的到期日。",
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

    print(f"{symbol} 期权波动率分析(到期 {expiry},剩余 {iv_days:.1f} 天,HV 窗口 {window} 日)")
    print(f"  正股现价:     {price}{price_source_note(symbol)}")
    print(f"  ATM IV({option_type}):  {result['iv_pct']}%")
    print(f"  HV({window}日年化):    {result['hv_pct'] if result['hv_pct'] is not None else 'N/A'}%")
    print(f"  IV/HV 比率:   {result['iv_hv_ratio']}")
    print(f"  判断:         {result['valuation'] or '无法判断(HV 数据不足)'}")
    if tenor_warning:
        print(f"  ⚠️ {tenor_warning}")
    print(f"  注: HV 为本地计算值,与 Futu 服务端 HV 可能有细微差异")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="期权波动率分析(IV vs HV)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--expiry", default=None,
                        help="到期日 YYYY-MM-DD(默认取剩余期限最接近 HV 窗口的到期日)")
    parser.add_argument("--hv-days", type=int, default=None,
                        help="HV 计算窗口,单位为交易日收益数(默认 30,约 43.5 个自然日);"
                             "指定 --expiry 而不给本参数时,自动取该到期日的自然日长度")
    parser.add_argument("--type", default="CALL", help="ATM IV 取 Call 还是 Put(默认 CALL)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        analyze(args.symbol, expiry=args.expiry, hv_days=args.hv_days,
                option_type=args.type, output_json=args.output_json)
    except Exception as e:
        print_error("期权波动率分析", str(e))
        sys.exit(1)
