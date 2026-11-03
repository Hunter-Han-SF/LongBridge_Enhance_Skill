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
import math
import os
import sys
from datetime import date

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    days_to_years,
    get_option_chain,
    market_now,
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
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_history(symbol: str, data: list[dict]) -> None:
    os.makedirs(_HISTORY_DIR, exist_ok=True)
    # pathlib 写汇(文件名经 _history_path 白名单净化+穿越防护)
    import pathlib as _pl
    _pl.Path(_history_path(symbol)).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


IV_TENOR_DAYS = 30


def get_current_atm_iv(symbol: str) -> tuple[float | None, dict | None]:
    """按期限插值总方差，返回恒定 30 日 ATM IV。"""
    spot = get_underlying_price(symbol)
    if not spot or spot <= 0:
        return None, None
    expirations = get_option_expirations(symbol)
    terms = [(days_to_years(expiry) * 365, expiry) for expiry in expirations]

    def sample(expiry: str):
        candidates = []
        for row in get_option_chain(symbol, expiry):
            if row.get("standard") is False:
                continue
            strike = to_float(row.get("strike"))
            vols = [to_float(row.get(key)) for key in ("call_iv", "put_iv")]
            vols = [vol for vol in vols if vol and vol > 0]
            if strike and strike > 0 and vols:
                candidates.append((strike, sum(vols) / len(vols)))
        return min(candidates, key=lambda item: abs(item[0] - spot), default=None)

    def nearest(terms):
        for days, expiry in terms:
            point = sample(expiry)
            if point:
                strike, vol = point
                return {"expiry": expiry, "days": days, "strike": strike, "iv": vol}
        return None

    left = nearest(sorted(((t, e) for t, e in terms if 0 < t <= IV_TENOR_DAYS), reverse=True))
    if left is None:
        return None, None
    if math.isclose(left["days"], IV_TENOR_DAYS, rel_tol=0, abs_tol=1e-9):
        return left["iv"], {"tenor_days": IV_TENOR_DAYS, "source_expiries": [left]}
    right = nearest(sorted((t, e) for t, e in terms if t > IV_TENOR_DAYS))
    if right is None:
        return None, None
    t0, t1 = left["days"], right["days"]
    w = (IV_TENOR_DAYS - t0) / (t1 - t0)
    variance = (1 - w) * left["iv"] ** 2 * t0 + w * right["iv"] ** 2 * t1
    return math.sqrt(variance / IV_TENOR_DAYS), {
        "tenor_days": IV_TENOR_DAYS, "source_expiries": [left, right]
    }


def _record_date(record: dict) -> date | None:
    if not isinstance(record, dict):
        return None
    raw_date = record.get("date")
    try:
        parsed = date.fromisoformat(raw_date)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.isoformat() == raw_date else None


def comparable_iv_series(history: list[dict]) -> list[dict]:
    """按观测日保留恒定期限样本，重复日期取最后一条有效记录。"""
    if not isinstance(history, list):
        return []
    series = {}
    for record in history:
        day = _record_date(record)
        if day is None or record.get("tenor_days") != IV_TENOR_DAYS:
            continue
        iv = to_float(record.get("atm_iv_pct"))
        if iv is not None and iv > 0:
            series[day] = dict(record, atm_iv_pct=iv)
    return [series[day] for day in sorted(series)]


def iv_history(
    symbol: str,
    append: bool = True,
    output_json: bool = False,
    quiet: bool = False,
) -> dict:
    observed_at = market_now(symbol)
    today = observed_at.date().isoformat()
    history = _load_history(symbol)

    # 追加今天
    appended = False
    if append:
        current_iv, meta = get_current_atm_iv(symbol)
        if current_iv is not None:
            # 避免同一天重复追加(覆盖当天)
            history = [h for h in history if not isinstance(h, dict) or h.get("date") != today]
            history.append({"date": today, "atm_iv_pct": round(current_iv * 100, 2),
                            "tenor_days": meta["tenor_days"],
                            "source_expiries": meta["source_expiries"],
                            "observed_at": observed_at.isoformat(), "quote_freshness": "unknown"})
            history.sort(key=lambda x: _record_date(x) or date.min)
            _save_history(symbol, history)
            appended = True

    if not history:
        raise ValueError(
            f"无历史 IV 数据。首次运行已尝试记录今天({today}),"
            "请多运行几次(建议每日)积累序列后再计算 IV Rank/Percentile。"
        )

    dates = sorted(day for row in history for day in [_record_date(row)] if day is not None)
    comparable = comparable_iv_series(history)
    result = {
        "symbol": symbol,
        "data_points": len(history),
        "date_range": f"{dates[0]} ~ {dates[-1]}" if dates else None,
        "comparable_points": len(comparable),
        "other_records": len(history) - len(comparable),
        "observed_at": observed_at.isoformat() if appended else None,
        "quote_freshness": "unknown",
        "appended_today": appended,
        "history_file": _history_path(symbol),
        "series": history,
        "note": "Longbridge 不提供历史 IV,新样本为恒定30日 ATM IV，旧样本保留但不可直接比较。观测时间为采集时间，行情新鲜度未知。",
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
    print(f"  可比恒定30日样本 {len(comparable)} 条，其他记录 {result['other_records']} 条")
    if appended:
        print(f"  观测时间: {result['observed_at']}，行情新鲜度未知")
    if comparable:
        ivs = [row["atm_iv_pct"] for row in comparable]
        print(f"  恒定30日 IV 区间: {min(ivs)}% ~ {max(ivs)}%  均值 {round(sum(ivs)/len(ivs), 2)}%")
        for row in comparable[-30:]:
            print(f"  {row['date']}  {row['atm_iv_pct']:>6}%")
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
