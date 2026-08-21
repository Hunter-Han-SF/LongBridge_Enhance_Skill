"""服务端量化指标/回测脚本(quant run,PineScript)。

对应 Longbridge CLI: quant run <SYMBOL> --start --end --script ... --language pine
用途:
  1. 跑本地没有的指标(服务端 ta.* 函数库)
  2. 与本地指标库(indicators.py)交叉验证(calc_indicators.py 的口径校对)
  3. 简单策略回测(strategy() 脚本,返回完整回测报告)

⚠️ 语言选择(实测 2026-08-21,CLI 0.27.1):
  - Navi(navi)服务端 internal server error(官方文档示例同样失败),不要用
  - PineScript(pine)正常 —— 本脚本内置预设全部用 pine
  - JSON 模式不返回 plot 序列值(CLI 缺口),指标模式解析 pretty 表拿
    First/Last/Min/Max;回测模式用 JSON 的 report_json(完整可用)

内置预设(无需自己写脚本):
  ema      — EMA20/60 双线
  rsi      — RSI(14)
  macd     — MACD(12,26,9),DIF/DEA/MACD
  backtest — EMA5/20 金叉死叉策略回测(返回净值/回撤/夏普等)
自定义: --script '<Pine代码>'(--language 默认 pine,可显式传 navi)

用法:
    python run_quant_indicator.py MSFT.US ema --start 2026-01-01
    python run_quant_indicator.py MSFT.US rsi --start 2026-01-01 --cross-check
    python run_quant_indicator.py MSFT.US macd --start 2026-06-01 --count 3
    python run_quant_indicator.py MSFT.US backtest --start 2025-01-01
    python run_quant_indicator.py 700.HK custom --start 2026-01-01 --script '...'
    python run_quant_indicator.py MSFT.US ema --start 2026-01-01 --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from common import (  # noqa: E402
    LongbridgeCliError,
    get_kline_adjusted,
    print_error,
    print_json,
    run_quant_script,
    to_float,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# 内置 Pine 预设(服务端引擎,PineScript 语法)
_PRESETS = {
    "ema": (
        'indicator("MA Cross", "ema fast slow", precision=2)\n'
        'x1 = input(20, "fast")\n'
        'x2 = input(60, "slow")\n'
        'plot(ta.ema(close, x1), "EMA Fast")\n'
        'plot(ta.ema(close, x2), "EMA Slow")\n'
    ),
    "rsi": (
        'indicator("RSI", "relative strength index", precision=2)\n'
        'len = input(14, "length")\n'
        'plot(ta.rsi(close, len), "RSI")\n'
    ),
    "macd": (
        'indicator("MACD", "12 26 9", precision=2)\n'
        '[a, b, c] = ta.macd(close, 12, 26, 9)\n'
        'plot(a, "DIF")\n'
        'plot(b, "DEA")\n'
        'plot(c, "MACD")\n'
    ),
    "backtest": (
        'strategy("EMA cross", overlay=true)\n'
        'x1 = input(5, "fast")\n'
        'x2 = input(20, "slow")\n'
        'emaFast = ta.ema(close, x1)\n'
        'emaSlow = ta.ema(close, x2)\n'
        'if ta.crossover(emaFast, emaSlow)\n'
        '    strategy.entry("long", strategy.long)\n'
        'if ta.crossunder(emaFast, emaSlow)\n'
        '    strategy.close("long")\n'
    ),
}


def parse_series_table(raw_output: str) -> dict[str, dict]:
    """解析 quant run pretty 输出的 Series 表。

    表格式(ANSI 已剥离):
        Series │ Bars│ First│ Last│ Min│ Max + Sparkline
    返回 {序列名: {bars, first, last, min, max}};数值字段取首个空白分隔 token。
    """
    out: dict[str, dict] = {}
    for line in _ANSI_RE.sub("", raw_output).splitlines():
        if "│" not in line:
            continue
        parts = line.split("│")
        if len(parts) < 6:
            continue
        name = parts[0].strip()
        if not name or name.lower() == "series":
            continue
        if not parts[1].strip().isdigit():
            continue

        def _num(field: str) -> float | None:
            token = field.strip().split()[0] if field.strip() else ""
            return to_float(token.lstrip("+"))

        vals = {
            "bars": int(parts[1].strip()),
            "first": _num(parts[2]),
            "last": _num(parts[3]),
            "min": _num(parts[4]),
            "max": _num(parts[5]),
        }
        if vals["last"] is not None:
            out[name] = vals
    return out


def parse_backtest_report(data: dict) -> dict:
    """从 quant run JSON 响应提取回测报告(report_json 是嵌套 JSON 字符串)。"""
    raw = data.get("report_json")
    if not raw or raw == "null":
        return {}
    report = json.loads(raw) if isinstance(raw, str) else raw
    perf = report.get("performanceAll") or {}
    keys = ("netProfit", "netProfitPercent", "maxDrawdown", "maxDrawdownPercent",
            "maxRunupPercent", "sharpeRatio", "sortinoRatio", "winRate",
            "lossRate", "numberOfWiningTrades", "numberOfLosingTrades",
            "profitFactor", "buyHoldReturnPercent", "totalTrades")
    stats = {}
    for k in keys:
        if perf.get(k) is not None:
            stats[k] = perf[k]
    for alias in ("totalClosedTrades", "totalOpenTrades"):
        if perf.get(alias) is not None and "totalTrades" not in stats:
            stats["totalTrades"] = perf[alias]
    return {"stats": stats, "config": report.get("config", {}),
            "raw_keys": list(report.keys())}


def _cross_check(symbol: str, series: dict[str, dict]) -> None:
    """用本地指标库(indicators.py)对服务端末值做口径校对。"""
    try:
        from indicators import ema, rsi  # noqa: E402 - technical/indicators.py
    except ImportError:
        print("(本地 indicators.py 不可用,跳过交叉验证)")
        return
    klines = get_kline_adjusted(symbol, count=300)
    closes = [k.get("close") for k in klines if k.get("close") is not None]
    if not closes:
        print("(无本地 K 线,跳过交叉验证)")
        return
    checks = []
    if "EMA Fast" in series and len(closes) >= 20:
        local = ema(closes, 20)
        checks.append(("EMA20", series["EMA Fast"]["last"], local))
    if "RSI" in series and len(closes) >= 15:
        local = rsi(closes, 14)
        checks.append(("RSI14", series["RSI"]["last"], local))
    if not checks:
        print("(无本地可对齐的序列,跳过交叉验证)")
        return
    print("\n🔍 交叉验证(服务端 vs 本地 indicators.py,末值):")
    for name, remote_v, local_v in checks:
        if remote_v is None or local_v is None:
            print(f"  {name}: 服务端 {remote_v},本地 {local_v}(一侧无数据)")
            continue
        diff = abs(remote_v - local_v)
        rel = diff / abs(local_v) if local_v else 0
        print(f"  {name}: 服务端 {remote_v:.4f} vs 本地 {local_v:.4f} "
              f"(相对偏差 {rel:.2%}{' ✅' if rel < 0.02 else ' ⚠️ 需检查口径'})")


def fetch_quant_indicator(
    symbol: str,
    preset: str = "ema",
    start: str | None = None,
    end: str | None = None,
    period: str = "day",
    script: str | None = None,
    script_file: str | None = None,
    language: str = "pine",
    cross_check: bool = False,
    count: int = 0,
    output_json: bool = False,
) -> dict:
    from datetime import date, timedelta
    end = end or date.today().strftime("%Y-%m-%d")
    if not start:
        start = (date.today() - timedelta(days=180)).strftime("%Y-%m-%d")

    if preset == "custom":
        if not script and not script_file:
            raise ValueError("custom 预设必须提供 --script '<Pine代码>' 或 --file <脚本路径>")
        lang = language
    else:
        if preset not in _PRESETS:
            raise ValueError(f"未知预设 {preset!r}。可选: {', '.join(_PRESETS)} 或 custom")
        script = _PRESETS[preset]
        lang = "pine"

    is_backtest = preset == "backtest" or (
        script is not None and "strategy(" in script)
    if lang == "navi":
        raise ValueError("Navi 服务端故障(实测 2026-08-21,官方示例同样 500),请用 pine")

    if is_backtest:
        # 回测:JSON 模式的 report_json 完整可用
        data = run_quant_script(symbol, start=start, end=end, period=period,
                                script=script, script_file=script_file if preset == "custom" else None,
                                language=lang)
        report = parse_backtest_report(data if isinstance(data, dict) else {})
        result = {"symbol": symbol, "preset": preset, "mode": "backtest",
                  "period": period, "start": start, "end": end, "report": report}
        if output_json:
            print_json(result)
            return result
        print(f"{symbol} 策略回测({preset},{period},{start} ~ {end})")
        stats = report.get("stats", {})
        if not stats:
            print("  (无回测统计,检查脚本是否含 strategy.entry/close)")
        else:
            label = {"netProfit": "净利润", "netProfitPercent": "净收益率%",
                     "maxDrawdownPercent": "最大回撤%", "sharpeRatio": "夏普",
                     "winRate": "胜率%", "totalTrades": "交易次数",
                     "buyHoldReturnPercent": "买入持有收益%"}
            for k, v in stats.items():
                zh = label.get(k, k)
                print(f"  {zh}: {v if isinstance(v, int) else round(v, 4) if isinstance(v, float) else v}")
        return result

    # 指标:JSON 模式缺 plot 值,解析 pretty 表
    raw = run_quant_script(symbol, start=start, end=end, period=period,
                           script=script, script_file=script_file if preset == "custom" else None,
                           language=lang, raw=True)
    series = parse_series_table(raw if isinstance(raw, str) else str(raw))
    result = {"symbol": symbol, "preset": preset, "mode": "indicator",
              "period": period, "start": start, "end": end,
              "series": series}

    if output_json:
        print_json(result)
        return result

    print(f"{symbol} 服务端指标 {preset}({period},{start} ~ {end})")
    if not series:
        print("  (未解析到序列,原始输出前 600 字):")
        print(_ANSI_RE.sub("", str(raw))[:600])
        return result
    for name, s in series.items():
        print(f"  {name}: {s['bars']} 根K线,最新 {s['last']}"
              f"(区间 {s['min']} ~ {s['max']})")
    if cross_check:
        _cross_check(symbol, series)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="服务端量化指标/回测(quant run,pine)")
    parser.add_argument("symbol", help="标的代码,如 MSFT.US / 700.HK")
    parser.add_argument("preset", nargs="?", default="ema",
                        choices=["ema", "rsi", "macd", "backtest", "custom"],
                        help="预设(默认 ema)")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD(默认 180 天前)")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD(默认今天)")
    parser.add_argument("--period", default="day",
                        choices=["1m", "5m", "15m", "30m", "1h", "day", "week", "month", "year"],
                        help="K 线周期(默认 day)")
    parser.add_argument("--script", default=None, help="custom 预设的内联脚本(Pine)")
    parser.add_argument("--file", dest="script_file", default=None, help="custom 预设的脚本文件路径")
    parser.add_argument("--language", default="pine", choices=["pine", "navi"],
                        help="脚本语言(默认 pine;navi 服务端故障中)")
    parser.add_argument("--cross-check", action="store_true", help="与本地指标库交叉验证末值")
    parser.add_argument("--count", type=int, default=0, help="兼容参数(指标统计不含逐bar序列)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON 格式")
    args = parser.parse_args()
    try:
        fetch_quant_indicator(
            symbol=args.symbol, preset=args.preset, start=args.start, end=args.end,
            period=args.period, script=args.script, script_file=args.script_file,
            language=args.language, cross_check=args.cross_check, count=args.count,
            output_json=args.output_json,
        )
    except Exception as e:
        print_error("运行服务端指标", str(e))
        sys.exit(1)
