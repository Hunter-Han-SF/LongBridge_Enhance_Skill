"""ATM IV 历史时间序列(B 档·本地累积，支持单股/批量/自选股每日自动记录)。

对应 Futu: get_option_underlying_his_volatility(IV 走势)

⚠️ 关键限制:Longbridge CLI 的 option chain 只返回实时数据,无法查询历史某天的 chain。
   因此本脚本采用"本地累积"模式:
   - 每次运行时,把当天的恒定30日 ATM IV 追加到本地数据文件(~/.lbr_iv_history/<symbol>.json，
     可通过环境变量 LBR_IV_HISTORY_DIR 自定义目录)
   - 支持单标的、多标的以及 --watchlist / --positions 批量采集
   - 日常问股(analyze_buy_sell / get_option_volatility / analyze_iv_crush / get_option_strategy)
     每日首次查询某美股时也会静默顺手记录当天的恒定30日 ATM IV

用法:
    python get_iv_history.py AAPL.US                # 追加今天 + 显示历史
    python get_iv_history.py AAPL.US MSFT.US NVDA.US # 批量采集多只美股
    python get_iv_history.py --watchlist             # 采集自选股中的所有美股
    python get_iv_history.py --positions             # 采集当前美股持仓
    python get_iv_history.py AAPL.US --no-append     # 只读不追加
    python get_iv_history.py AAPL.US --json
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
import sys
import threading
from datetime import date

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    LongbridgeCliError,
    calc_hv,
    days_to_years,
    get_batch_quotes,
    get_kline_adjusted,
    get_option_chain,
    get_option_expirations,
    get_stock_positions,
    get_underlying_price,
    get_watchlist_groups,
    is_equity_symbol,
    market_now,
    print_display_table,
    print_error,
    print_json,
    regular_session_price,
    to_float,
)

_DEFAULT_HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".lbr_iv_history")
_HISTORY_DIR = _DEFAULT_HISTORY_DIR
_SAVE_LOCK = threading.Lock()


def _effective_history_dir() -> str:
    """历史目录解析：优先测试用例 monkeypatch 的 _HISTORY_DIR，其次 LBR_IV_HISTORY_DIR。"""
    if _HISTORY_DIR != _DEFAULT_HISTORY_DIR:
        return _HISTORY_DIR
    env_dir = os.environ.get("LBR_IV_HISTORY_DIR", "").strip()
    return env_dir or _HISTORY_DIR


def _history_path(symbol: str) -> str:
    """symbol → 历史文件路径。白名单净化(仅字母数字_-)+ 穿越防护。"""
    import re as _re
    base_dir = _effective_history_dir()
    safe = _re.sub(r"[^A-Za-z0-9_-]", "_", str(symbol))[:64]
    path = os.path.join(base_dir, f"{safe}.json")
    # 防路径穿越:净化后文件名不得含路径分隔符,最终目录必须是历史目录本身
    if os.path.basename(path) != f"{safe}.json" or \
            os.path.dirname(os.path.abspath(path)) != os.path.abspath(base_dir):
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
    import pathlib as _pl
    base_dir = _effective_history_dir()
    with _SAVE_LOCK:
        os.makedirs(base_dir, exist_ok=True)
        # pathlib 写盘(文件名经 _history_path 白名单净化+穿越防护)
        _pl.Path(_history_path(symbol)).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


IV_TENOR_DAYS = 30


def get_current_atm_iv(symbol: str) -> tuple[float | None, dict | None]:
    """按期限插值总方差，返回恒定 30 日 ATM IV。"""
    latest = get_underlying_price(symbol)
    # chain 的 IV 是上一个常规时段的:盘前/盘后/夜盘运行时要用常规时段的 last 选 ATM,
    # 否则今天的样本会按延长时段的价格选行权价,与 IV 不在同一时点(见 common.regular_session_price)
    spot = regular_session_price(symbol, latest)
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


def maybe_record_daily_iv(symbol: str) -> bool:
    """机会式自动每日采集: 当今日恒定30日 ATM IV 尚未记录时静默落盘(<1ms 快速跳过已记标的)。

    任何网络/鉴权/非美股/无期权异常均静默返回 False，绝不阻塞主分析流程。
    可通过环境变量 LBR_AUTO_IV_RECORD=0 关闭。单元测试默认隔离(未改目录时不写宿主目录)。
    """
    try:
        sym = str(symbol or "").strip()
        if not sym or not sym.upper().endswith(".US") or not is_equity_symbol(sym):
            return False
        if os.environ.get("LBR_AUTO_IV_RECORD", "1").strip().lower() in {"0", "false", "no", "off"}:
            return False
        if ("unittest" in sys.modules
                and not os.environ.get("LBR_IV_HISTORY_DIR", "").strip()
                and _HISTORY_DIR == _DEFAULT_HISTORY_DIR):
            return False

        observed_at = market_now(sym)
        today = observed_at.date().isoformat()
        history = _load_history(sym)
        if any(
            isinstance(h, dict)
            and h.get("date") == today
            and h.get("tenor_days") == IV_TENOR_DAYS
            and (to_float(h.get("atm_iv_pct")) or 0) > 0
            for h in history
        ):
            return False

        current_iv, meta = get_current_atm_iv(sym)
        if current_iv is None or current_iv <= 0 or not meta:
            return False

        history = [h for h in history if not isinstance(h, dict) or h.get("date") != today]
        history.append({
            "date": today,
            "atm_iv_pct": round(current_iv * 100, 2),
            "tenor_days": meta["tenor_days"],
            "source_expiries": meta["source_expiries"],
            "observed_at": observed_at.isoformat(),
            "quote_freshness": "unknown",
        })
        history.sort(key=lambda x: _record_date(x) or date.min)
        _save_history(sym, history)
        return True
    except Exception:
        return False


def calc_hv_proxy_metrics(
    symbol: str,
    current_iv_pct: float,
    *,
    window: int = IV_TENOR_DAYS,
    lookback_bars: int = 285,
    kline_fn=None,
) -> dict | None:
    """基于过去约 1 年(252 交易日)滚动 30 日 HV 序列计算冷启动分位代理指标。"""
    fetch_kline = kline_fn or get_kline_adjusted
    klines = fetch_kline(symbol, count=lookback_bars)
    if not isinstance(klines, list) or not klines:
        return None
    closes = [
        c for row in klines if isinstance(row, dict)
        for c in [to_float(row.get("close"))]
        if c is not None and math.isfinite(c) and c > 0
    ]
    if len(closes) < window + 20:
        return None

    rolling_hvs: list[float] = []
    for idx in range(window + 1, len(closes) + 1):
        hv = calc_hv(closes[idx - (window + 1):idx])
        if hv is not None and math.isfinite(hv) and hv > 0:
            rolling_hvs.append(round(hv * 100, 2))
    if len(rolling_hvs) < 20:
        return None

    hv_current = rolling_hvs[-1]
    hv_lo = min(rolling_hvs)
    hv_hi = max(rolling_hvs)
    sv = sorted(rolling_hvs)
    n = len(sv)
    hv_median = sv[n // 2] if n % 2 == 1 else (sv[n // 2 - 1] + sv[n // 2]) / 2
    if hv_hi > hv_lo:
        raw_rank = (current_iv_pct - hv_lo) / (hv_hi - hv_lo) * 100
        hv_rank = round(min(max(raw_rank, 0.0), 100.0), 1)
    else:
        hv_rank = 50.0
    hv_pct = round(sum(1 for v in rolling_hvs if v < current_iv_pct) / n * 100, 1)
    return {
        "hv_window_days": window,
        "rolling_samples": n,
        "hv_current_pct": hv_current,
        "hv_low_pct": hv_lo,
        "hv_high_pct": hv_hi,
        "hv_median_pct": round(hv_median, 2),
        "hv_proxy_rank": hv_rank,
        "hv_proxy_percentile": hv_pct,
        "vrp_pct": round(current_iv_pct - hv_current, 2),
        "iv_hv_ratio": round(current_iv_pct / hv_current, 3) if hv_current > 0 else None,
        "above_hv_52w_high": current_iv_pct > hv_hi,
        "below_hv_52w_low": current_iv_pct < hv_lo,
    }


def check_series_continuity(
    series: list[dict],
    observed_day: str | None = None,
    min_points: int = 20,
) -> str | None:
    """检查本地可比 IV 序列是否存在长断档或近期密度过低。"""
    dates = sorted(d for row in series for d in [_record_date(row)] if d is not None)
    if len(dates) < 2:
        return None
    last_gap = (dates[-1] - dates[-2]).days
    ref_d = date.fromisoformat(observed_day) if observed_day else dates[-1]
    recent_60d = sum(1 for d in dates if 0 <= (ref_d - d).days <= 60)
    if last_gap > 14 or (len(dates) >= 5 and recent_60d < min(5, min_points)):
        return f"近60日仅 {recent_60d} 个观测点(最近两次间隔 {last_gap} 天)，样本存在断档"
    return None


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


def resolve_iv_symbols(
    symbols: list[str] | None = None,
    *,
    use_watchlist: bool = False,
    group: str | None = None,
    use_positions: bool = False,
) -> tuple[list[str], list[str]]:
    """合并显式代码 / 自选股 / 持仓，过滤为去重后的美股正股(.US)与被跳过清单。"""
    raw: list[str] = [str(s or "").strip() for s in (symbols or []) if str(s or "").strip()]
    if use_watchlist or group:
        for grp in get_watchlist_groups(group=group, market=None) or []:
            for sec in grp.get("securities") or []:
                sym = str(sec.get("symbol") or "").strip()
                if sym:
                    raw.append(sym)
    if use_positions:
        for pos in get_stock_positions(market=None) or []:
            sym = str(pos.get("symbol") or "").strip()
            if sym:
                raw.append(sym)

    us_symbols: list[str] = []
    skipped: list[str] = []
    seen_us: set[str] = set()
    seen_skip: set[str] = set()
    for sym in raw:
        up = sym.upper()
        if is_equity_symbol(sym) and up.endswith(".US"):
            if up not in seen_us:
                seen_us.add(up)
                us_symbols.append(sym)
        else:
            if up not in seen_skip:
                seen_skip.add(up)
                skipped.append(sym)
    return us_symbols, skipped


def batch_iv_history(
    symbols: list[str],
    *,
    append: bool = True,
    output_json: bool = False,
    skipped: list[str] | None = None,
) -> dict:
    """批量采集或读取多只美股正股的恒定30日 ATM IV 历史。"""
    clean_syms = [str(s).strip() for s in (symbols or []) if str(s or "").strip()]
    if not clean_syms:
        raise ValueError("未解析到支持期权的美股正股代码(.US)")

    if append and len(clean_syms) > 1:
        try:
            get_batch_quotes(clean_syms)
        except LongbridgeCliError as e:
            if "auth login" in str(e):
                raise
        except Exception:
            pass

    def _collect_one(sym: str) -> dict:
        try:
            hist = iv_history(sym, append=append, output_json=False, quiet=True)
            comp = comparable_iv_series(hist.get("series", []))
            curr_iv = comp[-1]["atm_iv_pct"] if comp else None
            delta_iv = round(curr_iv - comp[-2]["atm_iv_pct"], 2) if len(comp) >= 2 and curr_iv is not None else None
            return {
                "symbol": sym,
                "ok": True,
                "atm_iv_pct": curr_iv,
                "delta_iv_pct": delta_iv,
                "comparable_points": hist["comparable_points"],
                "data_points": hist["data_points"],
                "appended_today": hist["appended_today"],
                "date_range": hist["date_range"],
                "history_file": hist["history_file"],
            }
        except Exception as e:
            return {"symbol": sym, "ok": False, "error": str(e)}

    workers = min(3, len(clean_syms))
    if workers <= 1:
        rows = [_collect_one(s) for s in clean_syms]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_collect_one, clean_syms))

    ok_rows = [r for r in rows if r["ok"]]
    failed_rows = [r for r in rows if not r["ok"]]
    result = {
        "mode": "batch",
        "total": len(clean_syms),
        "succeeded": len(ok_rows),
        "failed": len(failed_rows),
        "skipped_non_us": list(skipped or []),
        "appended": append,
        "history_dir": _effective_history_dir(),
        "results": rows,
        "note": "恒定30日 ATM IV 批量采集/读取结果，仅覆盖美股正股(.US)。",
    }

    if output_json:
        print_json(result)
        return result

    action = "采集并落盘" if append else "只读汇总"
    print(f"批量 ATM IV {action}({len(ok_rows)}/{len(clean_syms)} 成功,目录 {_effective_history_dir()})")
    if skipped:
        print(f"  已跳过非美股正股({len(skipped)}): {', '.join(skipped)}")
    print()
    table_rows = []
    for r in rows:
        if r["ok"]:
            iv_s = f"{r['atm_iv_pct']:.2f}%" if r.get("atm_iv_pct") is not None else "N/A"
            chg_s = f"{r['delta_iv_pct']:+.2f}%" if r.get("delta_iv_pct") is not None else "-"
            status_s = "✓ 已记录" if r.get("appended_today") else "已读取"
            table_rows.append({
                "代码": r["symbol"],
                "30日ATM IV": iv_s,
                "较前日": chg_s,
                "可比点数": r["comparable_points"],
                "区间": r.get("date_range") or "-",
                "状态": status_s,
            })
        else:
            table_rows.append({
                "代码": r["symbol"],
                "30日ATM IV": "-",
                "较前日": "-",
                "可比点数": "-",
                "区间": "-",
                "状态": f"✗ {str(r['error'])[:36]}",
            })
    print_display_table(table_rows, columns=["代码", "30日ATM IV", "较前日", "可比点数", "区间", "状态"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ATM IV 历史序列(本地累积/批量采集)")
    parser.add_argument("symbols", nargs="*", help="正股代码列表,如 AAPL.US MSFT.US")
    parser.add_argument("--watchlist", action="store_true", help="采集自选股中的所有美股正股")
    parser.add_argument("--group", default=None, help="仅采集指定自选分组(配合 --watchlist)")
    parser.add_argument("--positions", action="store_true", help="采集当前账户的美股正股持仓")
    parser.add_argument("--no-append", action="store_true", help="只读不追加当天数据")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        if not args.watchlist and not args.positions and not args.group:
            if len(args.symbols) == 1:
                iv_history(args.symbols[0], append=not args.no_append, output_json=args.output_json)
            elif len(args.symbols) == 0:
                parser.error("请提供至少一个标的代码，或使用 --watchlist / --positions")
            else:
                us_syms, skipped = resolve_iv_symbols(args.symbols)
                batch_iv_history(us_syms, append=not args.no_append,
                                 output_json=args.output_json, skipped=skipped)
        else:
            us_syms, skipped = resolve_iv_symbols(
                args.symbols, use_watchlist=args.watchlist,
                group=args.group, use_positions=args.positions,
            )
            batch_iv_history(us_syms, append=not args.no_append,
                             output_json=args.output_json, skipped=skipped)
    except Exception as e:
        print_error("IV 历史", str(e))
        sys.exit(1)
