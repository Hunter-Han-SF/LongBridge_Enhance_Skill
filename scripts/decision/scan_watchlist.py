"""自选股/持仓批量扫描器(Batch Scanner: --fast 快速形态/技术扫雷 + --full 六维聚合)。

特性:
  1. 一次批量 `quote` 预热行情并回填进程内 CLI 缓存;大盘 Regime 仅评估一次后全批共享
  2. 受控并发(`ThreadPoolExecutor`)配合线程安全限频 + K 线/基础面缓存,大幅压缩扫描耗时
  3. 支持显式标的、只读 `watchlist`(可选 `--group`)、只读 `positions` 三种标的水池
  4. 可选按 `--capital` / `--use-account` 与止损位同步输出每只候选股的建议定仓股数

用法:
    python scan_watchlist.py                          # 扫描全部美股自选(--fast)
    python scan_watchlist.py --group 核心池 --full    # 指定自选分组跑完整六维仪表盘
    python scan_watchlist.py --positions --capital 50000
    python scan_watchlist.py AAPL.US MSFT.US NVDA.US --capital 50000
    python scan_watchlist.py --only-setups --json
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import io
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (
    os.path.normpath(os.path.join(_HERE, "..")),
    _HERE,
    os.path.normpath(os.path.join(_HERE, "..", "technical")),
    os.path.normpath(os.path.join(_HERE, "..", "fundamental")),
    os.path.normpath(os.path.join(_HERE, "..", "quote")),
    os.path.normpath(os.path.join(_HERE, "..", "market")),
    os.path.normpath(os.path.join(_HERE, "..", "calendar")),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common  # noqa: E402
from common import (  # noqa: E402
    get_account_assets,
    get_batch_quotes,
    get_finance_calendar,
    get_kline_adjusted,
    get_stock_positions,
    get_underlying_quote,
    get_watchlist_groups,
    is_equity_symbol,
    kline_last_bar_in_progress,
    latest_underlying_price,
    market_date,
    market_now,
    parse_underlying,
    print_display_table,
    print_error,
    print_json,
    to_float,
)
from analyze_buy_sell import analyze as dashboard_analyze  # noqa: E402
from calc_technical_score import score as tech_score  # noqa: E402
from check_entry_rules import (  # noqa: E402
    _auto_d11,
    _auto_d6,
    _closed_dates,
    build_features,
    calc_position_sizing,
    check_rules,
)
from get_market_regime import assess_market_regime  # noqa: E402

_MARKET_CCY = {"US": "USD", "HK": "HKD", "CN": "CNY", "SH": "CNY", "SZ": "CNY", "SG": "SGD"}


def _nearest_earnings_days(symbol: str, market: str, today) -> int | None:
    try:
        buckets = get_finance_calendar(category="report", market=market, symbol=symbol, count=20)
        best = None
        for b in buckets or []:
            for info in (b or {}).get("infos") or []:
                d = str((info or {}).get("date") or "").replace(".", "-")[:10]
                try:
                    days = (datetime.strptime(d, "%Y-%m-%d").date() - today).days
                except ValueError:
                    continue
                if days >= 0 and (best is None or days < best):
                    best = days
        return best
    except Exception:
        return None


def _resolve_universe(
    symbols: list[str] | None = None,
    use_watchlist: bool = False,
    group: str | None = None,
    use_positions: bool = False,
    market: str = "US",
    limit: int = 30,
) -> list[dict]:
    """合并显式标的 / 只读自选分组 / 只读持仓，去重并限制上限。"""
    mkt = (market or "US").upper()
    items: list[dict] = []
    seen: set[str] = set()

    def _add(sym: str, name: str = "", source: str = "manual",
             qty: float | None = None, cost_price: float | None = None) -> None:
        s = str(sym or "").strip().upper()
        if not s or not is_equity_symbol(s):
            return
        smkt = parse_underlying(s)[1]
        if mkt != "ALL" and smkt != mkt:
            return
        if s in seen:
            return
        seen.add(s)
        items.append({
            "symbol": s,
            "name": name,
            "source": source,
            "position_qty": qty,
            "cost_price": cost_price,
        })

    for raw in symbols or []:
        _add(raw, source="cli")

    if use_positions:
        for p in get_stock_positions(market=mkt):
            _add(
                p.get("symbol", ""),
                name=str(p.get("name") or ""),
                source="position",
                qty=to_float(p.get("quantity")),
                cost_price=to_float(p.get("cost_price")),
            )

    auto_wl = use_watchlist or bool(group) or (not symbols and not use_positions)
    if auto_wl:
        for g in get_watchlist_groups(group=group, market=mkt):
            gname = str(g.get("name") or "自选")
            for sec in g.get("securities") or []:
                _add(
                    sec.get("symbol", ""),
                    name=str(sec.get("name") or ""),
                    source=f"watchlist:{gname}",
                )

    cap = max(1, int(limit or 30))
    return items[:cap]


def _scan_one_symbol(
    meta: dict,
    *,
    quotes: dict[str, dict],
    closed_by_mkt: dict[str, set[str]],
    mode: str,
    include_regime: bool,
    capital: float | None,
    risk_pct: float,
    max_pos_pct: float,
    max_stop_pct: float,
    lookback: int,
) -> dict:
    sym = meta["symbol"]
    _, mkt = parse_underlying(sym)
    now = market_now(mkt)
    try:
        q = quotes.get(sym.upper()) or get_underlying_quote(sym)
        latest_px, px_info = latest_underlying_price(q, now)
        reg_px = to_float((q or {}).get("regular_price"))
        px_src = (px_info or {}).get("source") or "regular"
        src_label = (px_info or {}).get("source_label") or "常规时段"
        ext_chg_pct = (
            round((latest_px - reg_px) / reg_px * 100.0, 2)
            if px_src != "regular" and latest_px and reg_px and reg_px > 0
            else None
        )
        chg_pct = ext_chg_pct if ext_chg_pct is not None else to_float((q or {}).get("change_percentage"))

        raw_bars = get_kline_adjusted(sym, count=260)
        bars = [
            b for b in (raw_bars or [])
            if isinstance(b, dict) and all(to_float(b.get(k)) is not None for k in ("open", "close", "high", "low"))
        ]
        if len(bars) < 30:
            raise ValueError(f"有效日K不足30根({len(bars)})")

        intraday = kline_last_bar_in_progress(bars, sym, now)
        eff_bars = bars[:-1] + [dict(bars[-1], volume=None)] if intraday else bars
        f = build_features(eff_bars, sym)

        ref_px = reg_px if (reg_px is not None and reg_px > 0) else f["last"]
        earn_days = _nearest_earnings_days(sym, mkt, now.date())

        opts = {
            "entry_price": ref_px,
            "quote_available": bool(reg_px and reg_px > 0),
            "latest_bar_valid": True,
            "intraday_bar": intraday,
            "lookback": lookback,
            "max_stop_pct": max_stop_pct,
            "earnings_days": earn_days,
            "closed_dates": closed_by_mkt.get(mkt, set()),
            "market": mkt,
            "now": now,
            "d6_auto": _auto_d6(sym, f, intraday_bar=True, industry_info=None),
            "d11_auto": _auto_d11(sym, px_info, f["atr_pct"], earn_days),
        }
        er = check_rules(f, opts)
        stop = er["levels"].get("support")
        target = er["levels"].get("target")
        rr = er["levels"].get("rr")
        stop_dist_pct = (
            round((ref_px - stop) / ref_px * 100.0, 2)
            if (stop is not None and ref_px and ref_px > 0 and stop < ref_px)
            else None
        )
        stop_breached_ext = bool(
            px_src != "regular" and latest_px is not None and stop is not None and latest_px <= stop
        )

        tech_sc = tech_label = None
        if len(bars) >= 60:
            try:
                t_res = tech_score(sym, count=260, quiet=True)
                tech_sc = t_res.get("technical_score")
                tech_label = t_res.get("label")
            except Exception:
                tech_sc = None

        comp_sc = sig_label = None
        if mode == "full":
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    d_res = dashboard_analyze(sym, output_json=False, include_regime=include_regime)
                comp_sc = d_res.get("composite_score")
                sig_label = d_res.get("signal")
            except Exception:
                comp_sc = None

        sizing = None
        if capital is not None and capital > 0:
            sizing = calc_position_sizing(
                ref_px, stop, capital,
                risk_pct=risk_pct, max_pos_pct=max_pos_pct,
                currency=_MARKET_CCY.get(mkt, "USD"),
                ext_price=latest_px if px_src != "regular" else None,
            )

        cost = meta.get("cost_price")
        pl_pct = (
            round((latest_px - cost) / cost * 100.0, 2)
            if (cost and cost > 0 and latest_px is not None)
            else None
        )

        return {
            "symbol": sym,
            "name": meta.get("name", ""),
            "source": meta.get("source", ""),
            "market": mkt,
            "status": "ok",
            "price": round(latest_px, 2) if latest_px is not None else round(ref_px, 2),
            "regular_price": round(reg_px, 2) if reg_px is not None else round(f["last"], 2),
            "price_source": px_src,
            "source_label": src_label,
            "change_pct": round(chg_pct, 2) if chg_pct is not None else None,
            "context": er["context"],
            "technical_score": tech_sc,
            "technical_label": tech_label,
            "composite_score": comp_sc,
            "signal": sig_label,
            "matched": er["matched"],
            "triggered": er["triggered"],
            "verdict": er["verdict"],
            "stop": round(stop, 2) if stop is not None else None,
            "stop_dist_pct": stop_dist_pct,
            "target": round(target, 2) if target is not None else None,
            "rr": round(rr, 2) if rr is not None else None,
            "earnings_days": earn_days,
            "stop_breached_ext": stop_breached_ext,
            "position_qty": meta.get("position_qty"),
            "cost_price": cost,
            "unrealized_pl_pct": pl_pct,
            "recommended_shares": sizing.get("recommended_shares") if isinstance(sizing, dict) else None,
            "position_sizing": sizing,
        }
    except Exception as e:
        return {
            "symbol": sym,
            "name": meta.get("name", ""),
            "source": meta.get("source", ""),
            "market": mkt,
            "status": "error",
            "error": str(e)[:80],
            "matched": [],
            "triggered": [],
        }


def _sort_items(items: list[dict], sort_by: str, mode: str) -> list[dict]:
    def key_fn(it: dict):
        if it.get("status") != "ok":
            return (1, 1, 1, 9999.0, 9999.0)
        matched = it.get("matched") or []
        triggered = it.get("triggered") or []
        rr = it.get("rr")
        tech = it.get("technical_score")
        comp = it.get("composite_score")
        chg = it.get("change_pct")

        if sort_by == "tech":
            return (0, -(tech if tech is not None else -999.0), -(rr if rr is not None else -999.0))
        if sort_by == "composite":
            score_v = comp if comp is not None else (tech if tech is not None else -999.0)
            return (0, -score_v, -(rr if rr is not None else -999.0))
        if sort_by == "change":
            return (0, -(chg if chg is not None else -999.0))
        if sort_by == "rr":
            return (0, -(rr if rr is not None else -999.0), -(tech if tech is not None else -999.0))

        # actionable(默认): 命中买点且无硬阻断优先 → 再按无硬阻断与评分降序
        clean_setup = bool(matched) and not triggered and (rr is None or rr >= 1.0)
        primary_score = comp if (mode == "full" and comp is not None) else (tech if tech is not None else -1.0)
        return (
            0,
            0 if clean_setup else 1,
            0 if not triggered else 1,
            -len(matched),
            -primary_score,
            -(rr if rr is not None else -1.0),
        )

    return sorted(items, key=key_fn)


def scan_watchlist(
    symbols: list[str] | None = None,
    *,
    use_watchlist: bool = False,
    group: str | None = None,
    use_positions: bool = False,
    market: str = "US",
    mode: str = "fast",
    sort_by: str = "actionable",
    only_setups: bool = False,
    limit: int = 30,
    workers: int = 4,
    capital: float | None = None,
    use_account: bool = False,
    risk_pct: float = 1.0,
    max_pos_pct: float = 20.0,
    max_stop_pct: float = 8.0,
    lookback: int = 60,
    include_regime: bool = True,
    output_json: bool = False,
) -> dict:
    universe = _resolve_universe(
        symbols=symbols,
        use_watchlist=use_watchlist,
        group=group,
        use_positions=use_positions,
        market=market,
        limit=limit,
    )
    if not universe:
        raise ValueError("未找到符合条件的扫描标的(可检查自选组名、持仓或显式传入代码)。")

    # 共享预热: 1 次批量报价(顺带回填单票缓存) + 每市场 1 次大盘环境 + 休市日历
    quotes = get_batch_quotes([u["symbol"] for u in universe])
    unique_mkts = []
    for u in universe:
        _, m = parse_underlying(u["symbol"])
        if m not in unique_mkts:
            unique_mkts.append(m)

    regimes: dict[str, dict] = {}
    if include_regime:
        for m in unique_mkts:
            try:
                regimes[m] = assess_market_regime(m)
            except Exception:
                pass

    closed_by_mkt: dict[str, set[str]] = {}
    for m in unique_mkts:
        try:
            closed_by_mkt[m] = _closed_dates(m)
        except Exception:
            closed_by_mkt[m] = set()

    eff_cap = capital
    cap_currency = _MARKET_CCY.get(unique_mkts[0] if unique_mkts else "US", "USD")
    if eff_cap is None and use_account:
        try:
            assets = get_account_assets(cap_currency)
            eff_cap = to_float(assets.get("net_assets"))
            if assets.get("currency"):
                cap_currency = assets["currency"]
        except Exception:
            eff_cap = None

    max_w = max(1, min(int(workers or 4), len(universe), 6))
    results: list[dict] = []
    if max_w == 1 or len(universe) == 1:
        for meta in universe:
            results.append(_scan_one_symbol(
                meta, quotes=quotes, closed_by_mkt=closed_by_mkt,
                mode=mode, include_regime=include_regime,
                capital=eff_cap, risk_pct=risk_pct, max_pos_pct=max_pos_pct,
                max_stop_pct=max_stop_pct, lookback=lookback,
            ))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_w) as pool:
            futs = [
                pool.submit(
                    _scan_one_symbol, meta,
                    quotes=quotes, closed_by_mkt=closed_by_mkt,
                    mode=mode, include_regime=include_regime,
                    capital=eff_cap, risk_pct=risk_pct, max_pos_pct=max_pos_pct,
                    max_stop_pct=max_stop_pct, lookback=lookback,
                )
                for meta in universe
            ]
            for fut in futs:
                results.append(fut.result())

    if only_setups:
        filtered = [r for r in results if r.get("status") == "ok" and r.get("matched")]
    else:
        filtered = results

    sorted_items = _sort_items(filtered, sort_by=sort_by, mode=mode)
    ok_items = [r for r in results if r.get("status") == "ok"]
    setup_cnt = sum(1 for r in ok_items if r.get("matched"))
    blocked_cnt = sum(1 for r in ok_items if r.get("triggered"))
    err_cnt = len(results) - len(ok_items)

    out = {
        "mode": mode,
        "market": market.upper(),
        "scanned": len(results),
        "ok_count": len(ok_items),
        "setup_count": setup_cnt,
        "blocked_count": blocked_cnt,
        "error_count": err_cnt,
        "only_setups": only_setups,
        "sort_by": sort_by,
        "capital": eff_cap,
        "currency": cap_currency if eff_cap is not None else None,
        "market_regimes": regimes or None,
        "items": sorted_items,
    }

    if output_json:
        print_json(out)
        return out

    mode_lbl = "完整六维(--full)" if mode == "full" else "快速扫雷(--fast)"
    print(f"🔎 批量扫描 [{mode_lbl}]  共 {len(results)} 只  |  命中买点 {setup_cnt} 只  |  触发不买 {blocked_cnt} 只")
    for m, reg in regimes.items():
        if isinstance(reg, dict) and reg.get("regime") != "unknown":
            print(f"  🧭 {m} 大盘环境: {reg.get('label', '')} — {reg.get('summary', '')}")
    if eff_cap is not None:
        print(f"  💰 定仓口径: 总资金 {eff_cap:,.0f} {cap_currency}  |  单笔风险 {risk_pct}%  |  单票上限 {max_pos_pct}%")
    print()

    if not sorted_items:
        print("  (当前过滤条件下无匹配标的)")
        return out

    rows = []
    has_sizing = eff_cap is not None
    has_pos = any(r.get("unrealized_pl_pct") is not None for r in sorted_items)
    for r in sorted_items:
        if r.get("status") != "ok":
            rows.append({
                "代码": r["symbol"],
                "现价": "ERROR",
                "涨跌%": "-",
                "背景": "-",
                "评分": "-",
                "买点": "-",
                "不买阻断": r.get("error", "")[:22],
                "止损/盈亏比": "-",
                "建议股数": "-",
                "财报": "-",
            })
            continue
        src = f"({r['source_label']})" if r.get("price_source") != "regular" else ""
        chg_s = f"{r['change_pct']:+.2f}%" if r.get("change_pct") is not None else "-"
        sc_v = r.get("composite_score") if mode == "full" and r.get("composite_score") is not None else r.get("technical_score")
        sc_s = f"{sc_v:.0f}" if sc_v is not None else "-"
        if mode == "full" and r.get("signal"):
            sc_s = f"{sc_s} {r['signal'][:2]}"
        mat_s = ",".join(r["matched"]) or "-"
        tri_s = ",".join(r["triggered"]) or "✅"
        if r.get("stop") is not None:
            rr_s = f"{r['rr']:.1f}:1" if r.get("rr") is not None else "-"
            breach = "⚠️已破!" if r.get("stop_breached_ext") else ""
            stop_s = f"{r['stop']:.2f}(-{r['stop_dist_pct']:.1f}%) {rr_s}{breach}"
        else:
            stop_s = "无明确止损"
        earn_s = f"{r['earnings_days']}d" if r.get("earnings_days") is not None else "-"
        row = {
            "代码": r["symbol"],
            "现价": f"{r['price']:.2f}{src}",
            "涨跌%": chg_s,
            "背景": r.get("context", "-")[:4],
            "评分": sc_s,
            "买点": mat_s,
            "不买阻断": tri_s,
            "止损/盈亏比": stop_s,
            "财报": earn_s,
        }
        if has_sizing:
            row["建议股数"] = f"{r['recommended_shares']}股" if r.get("recommended_shares") is not None else "-"
        if has_pos:
            row["持仓浮盈"] = f"{r['unrealized_pl_pct']:+.1f}%" if r.get("unrealized_pl_pct") is not None else "-"
        rows.append(row)

    cols = ["代码", "现价", "涨跌%", "背景", "评分", "买点", "不买阻断", "止损/盈亏比"]
    if has_sizing:
        cols.append("建议股数")
    if has_pos:
        cols.append("持仓浮盈")
    cols.append("财报")
    print_display_table(rows, columns=cols)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自选股/持仓批量扫描器")
    parser.add_argument("symbols", nargs="*", help="显式指定标的代码(留空默认扫描自选股)")
    parser.add_argument("--watchlist", action="store_true", help="扫描只读自选股")
    parser.add_argument("--group", default=None, help="仅扫描指定自选股分组名称或ID")
    parser.add_argument("--positions", action="store_true", help="扫描当前账户正股持仓")
    parser.add_argument("--market", default="US", choices=["US", "HK", "CN", "SG", "ALL"],
                        help="过滤市场(默认 US;ALL 不过滤)")
    parser.add_argument("--mode", choices=["fast", "full"], default="fast",
                        help="扫描深度: fast(技术+军规形态,默认) / full(含六维决策仪表盘)")
    parser.add_argument("--full", action="store_true", help="等价于 --mode full")
    parser.add_argument("--sort", choices=["actionable", "tech", "composite", "change", "rr"],
                        default="actionable", help="排序方式(默认 actionable 买点无阻断优先)")
    parser.add_argument("--only-setups", action="store_true", help="仅显示命中买点结构(B1-B9)的标的")
    parser.add_argument("--limit", type=int, default=30, help="最多扫描标的数(默认 30)")
    parser.add_argument("--workers", type=int, default=4, help="并发线程数(默认 4,上限 6)")
    parser.add_argument("--capital", type=float, default=None, help="风险定仓: 指定总资金")
    parser.add_argument("--use-account", action="store_true", help="风险定仓: 读取只读账户净资产")
    parser.add_argument("--risk-pct", type=float, default=1.0, help="单笔风险上限%%(默认 1.0)")
    parser.add_argument("--max-pos-pct", type=float, default=20.0, help="单票仓位上限%%(默认 20.0)")
    parser.add_argument("--max-stop-pct", type=float, default=8.0, help="最大止损承受力%%(默认 8.0)")
    parser.add_argument("--lookback", type=int, default=60, help="新高/新低回看天数(默认 60)")
    parser.add_argument("--no-regime", action="store_true", help="跳过大盘环境评估")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        scan_watchlist(
            symbols=args.symbols or None,
            use_watchlist=args.watchlist,
            group=args.group,
            use_positions=args.positions,
            market=args.market,
            mode="full" if args.full else args.mode,
            sort_by=args.sort,
            only_setups=args.only_setups,
            limit=args.limit,
            workers=args.workers,
            capital=args.capital,
            use_account=args.use_account,
            risk_pct=args.risk_pct,
            max_pos_pct=args.max_pos_pct,
            max_stop_pct=args.max_stop_pct,
            lookback=args.lookback,
            include_regime=not args.no_regime,
            output_json=args.output_json,
        )
    except Exception as e:
        print_error("批量扫描自选", str(e))
        sys.exit(1)
