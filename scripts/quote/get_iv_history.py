"""ATM IV 历史时间序列(B 档·本地累积)。

对应 Futu: get_option_underlying_his_volatility(IV 走势)

⚠️ 关键限制:Longbridge CLI 的 option chain 只返回实时数据,无法查询历史某天的 chain。
   因此本脚本采用"本地累积"模式:
   - 每次运行时,把当天的 ATM IV 追加到本地数据文件(~/.lbr_iv_history/<symbol>.json)
   - 历史序列靠多次运行逐步积累
   - 首次运行只有 1 个数据点,需持续运行多天才能得到有意义的序列

建议配合 cron / 定时任务每日运行一次。

用法:
    python get_iv_history.py AAPL.US          # 追加今天 + 显示历史
    python get_iv_history.py AAPL.US --no-append  # 只读不追加
    python get_iv_history.py AAPL.US --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    get_option_chain,
    get_option_expirations,
    get_underlying_price,
    print_error,
    print_json,
    to_float,
)

_HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".lbr_iv_history")


def _history_path(symbol: str) -> str:
    """symbol → 历史文件路径。白名单净化(仅字母数字_-)+ 穿越防护。"""
    import re as _re
    safe = _re.sub(r"[^A-Za-z0-9_-]", "_", str(symbol))[:64]
    path = os.path.join(_HISTORY_DIR, f"{safe}.json")
    # 防路径穿越:净化后文件名不得含路径分隔符,最终目录必须是历史目录本身
    if os.path.basename(path) != f"{safe}.json" or \
            os.path.dirname(os.path.abspath(path)) != os.path.abspath(_HISTORY_DIR):
        raise ValueError(f"非法 symbol: {symbol!r}")
    return path


def _load_history(symbol: str) -> list[dict]:
    path = _history_path(symbol)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_history(symbol: str, data: list[dict]) -> None:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    # pathlib 写汇(文件名经 _history_path 白名单净化+穿越防护)
    import pathlib as _pl
    _pl.Path(_history_path(symbol)).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_current_atm_iv(symbol: str) -> tuple[float | None, dict | None]:
    """取当前 ATM IV(流动性最好的行权价的 call+put IV 均值)。返回 (iv, 元信息)。"""
    expirations = get_option_expirations(symbol)
    if not expirations:
        return None, None
    # 取最近的月度到期日
    monthly = [e for e in expirations if 15 <= int(e[8:10]) <= 21] or expirations
    expiry = monthly[0]
    chain = get_option_chain(symbol, expiry)
    if not chain:
        return None, None

    # 用流动性最好的行权价作为 ATM 近似
    best, best_vol = None, -1
    for r in chain:
        vol = (to_float(r.get("call_vol")) or 0) + (to_float(r.get("put_vol")) or 0)
        if vol > best_vol:
            best_vol, best = vol, r
    if not best:
        return None, None
    civ = to_float(best.get("call_iv"))
    piv = to_float(best.get("put_iv"))
    vals = [v for v in (civ, piv) if v and v > 0]
    if not vals:
        return None, None
    iv = sum(vals) / len(vals)
    return iv, {"expiry": expiry, "strike": to_float(best.get("strike")),
                "call_iv": civ, "put_iv": piv}


def iv_history(
    symbol: str,
    append: bool = True,
    output_json: bool = False,
    quiet: bool = False,
) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    history = _load_history(symbol)

    # 追加今天
    appended = False
    if append:
        current_iv, meta = get_current_atm_iv(symbol)
        if current_iv is not None:
            # 避免同一天重复追加(覆盖当天)
            history = [h for h in history if h.get("date") != today]
            history.append({"date": today, "atm_iv_pct": round(current_iv * 100, 2),
                            "expiry": meta.get("expiry"), "strike": meta.get("strike")})
            history.sort(key=lambda x: x["date"])
            _save_history(symbol, history)
            appended = True

    if not history:
        raise ValueError(
            f"无历史 IV 数据。首次运行已尝试记录今天({today}),"
            "请多运行几次(建议每日)积累序列后再计算 IV Rank/Percentile。"
        )

    result = {
        "symbol": symbol,
        "data_points": len(history),
        "date_range": f"{history[0]['date']} ~ {history[-1]['date']}",
        "appended_today": appended,
        "history_file": _history_path(symbol),
        "series": history,
        "note": "Longbridge 不提供历史 IV,本序列靠本地累积。建议每日运行。",
    }

    if output_json:
        print_json(result)
        return result

    if quiet:
        return result

    print(f"{symbol} ATM IV 历史(本地累积 {len(history)} 个点)")
    print(f"  区间: {result['date_range']}")
    print(f"  {'✓ 已追加今天数据' if appended else '(未追加,--no-append)'}")
    print(f"  文件: {_history_path(symbol)}")
    ivs = [s["atm_iv_pct"] for s in history]
    print(f"  IV 区间: {min(ivs)}% ~ {max(ivs)}%  均值 {round(sum(ivs)/len(ivs),2)}%")
    print()
    for s in history[-30:]:  # 最多显示最近 30 个
        bar = "█" * int(s["atm_iv_pct"])
        print(f"  {s['date']}  {s['atm_iv_pct']:>6}%  {bar}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATM IV 历史序列(本地累积)")
    parser.add_argument("symbol", help="正股代码,如 AAPL.US")
    parser.add_argument("--no-append", action="store_true", help="只读不追加当天数据")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        iv_history(args.symbol, append=not args.no_append, output_json=args.output_json)
    except Exception as e:
        print_error("IV 历史", str(e))
        sys.exit(1)
