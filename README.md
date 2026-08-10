# LongBridge Enhance Skill (longbridge-pro)

**[English](README.md)** | [中文](README.zh-CN.md)

> Community-developed multi-dimensional analytics enhancement for the [Longbridge OpenAPI](https://open.longbridge.com).
> Five modules: ① Options analytics (BS Greeks, IV/HV, vol smile, P/C ratio, P&L, Put/Call Wall, GEX, IV Crush)
> ② Anomaly tracking ③ Capital flow / main force ④ Event calendar ⑤ Market sentiment — all computed locally from Longbridge CLI data.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What this is

The official `longbridge` skill series gives you **raw data** (option chains, quotes, fundamentals) via the Longbridge CLI. This enhancement skill adds the **compute and fusion layer on top** — Black-Scholes pricing, Greeks, volatility analysis, strategy P&L, anomaly scoring, capital-flow analytics, and a one-click daily market briefing that the raw CLI doesn't provide.

## Features

### 🟢 Module ①: Options analytics (US OPRA)
- **Option chain / expirations / P-C ratio / OCC resolver** — native data wrapped
- **Single-contract Greeks** — Delta / Gamma / Theta / Vega / Rho via Black-Scholes
- **IV vs HV** — implied vol (from chain) vs historical vol (from K-line)
- **Volatility smile & skew** — per-strike IV curve + put skew
- **IV Rank & IV Percentile** — via local accumulation
- **Exercise probability / Portfolio Greeks / Expiration P&L / 8 strategy legs**
- **Put/Call Wall** — largest-volume strikes as support/resistance
- **Gamma Exposure (GEX)** — dealer hedging pressure + zero-gamma flip point
- **Earnings IV Crush** — pre/post-earnings IV change with earnings calendar

### 🔵 Module ②: Anomaly tracking
- **Anomaly signals** — block trades, limit-up/down, with bull/bear emotion tags
- **Top movers** — stocks beating 20-day volatility bands, with correlated news
- **Anomaly composite score** — single-symbol 0-100 score fusing signals + capital flow + change + movers

### 💰 Module ③: Capital flow / main force
- **Capital distribution** — large/medium/small order inflow/outflow + net + minute-level flow series
- **HK broker holdings** — top-10 buy/sell brokers, full detail, single-broker history (HK only)
- **Short selling** — daily short-volume ratio + open interest (US days-to-cover / HK cost)

### 📅 Module ④: Event calendar
- **Earnings calendar** — estimated/actual EPS, published vs TBD
- **Dividend calendar** — amount, type (regular/special), payment date

### 🌡️ Module ⑤: Market sentiment
- **Market temperature** — 0-100 index + valuation/sentiment sub-scores + history
- **Heat rankings** — total heat / rising / trading / discussion / watchlist across markets
- **Daily briefing** — one-click aggregate (temp + heat top5 + movers top5 + anomaly stats + SPY P/C)

## Requirements

- **Longbridge CLI** installed and authenticated (`longbridge auth login`)
- **Python 3.8+** (no third-party packages — pure standard library)
- Options module needs **OPRA options market data** permission (modules ②–⑤ do not)

## Installation

### Option A: As a ZCode / Claude Code skill

Copy or symlink this folder to your skills directory:

```bash
# ZCode (symlink recommended — picks up edits live)
mklink /D %USERPROFILE%\.zcode\skills\longbridge-pro F:\path\to\LongBridge_Enhance_Skill

# Claude Code
cp -r LongBridge_Enhance_Skill ~/.claude/skills/longbridge-pro
```

Verify the environment:

```bash
python scripts/check_env.py
```

### Option B: Standalone scripts

```bash
git clone https://github.com/Hunter-Han-SF/LongBridge_Enhance_Skill.git
cd LongBridge_Enhance_Skill
python scripts/check_env.py
```

## Quick start

```bash
# === Options ===
python scripts/quote/get_option_volatility.py AAPL.US        # IV vs HV
python scripts/quote/get_put_call_wall.py AAPL.US --date 2026-09-18  # support/resistance

# === Anomaly & capital flow ===
python scripts/market/get_top_movers.py --market US          # movers + news
python scripts/flow/get_capital_flow.py AAPL.US --flow       # minute capital flow
python scripts/flow/get_broker_holding.py 700.HK --detail    # HK broker holdings

# === Calendar & sentiment ===
python scripts/calendar/get_earnings_calendar.py --market US
python scripts/sentiment/get_market_temp.py US

# === One-click daily briefing ===
python scripts/sentiment/daily_briefing.py --market US
```

See [`SKILL.md`](SKILL.md) for the full command reference.

## Known limitations

These are **data-source limitations** of the Longbridge API, not bugs:

1. **Single-contract `option quote` returns empty** — Greeks computed via Black-Scholes using chain IV.
2. **No historical IV** — IV Rank/Percentile use **local accumulation** (`get_iv_history.py` daily).
3. **US options only (OPRA)** — HK / A-share options return empty.
4. **No per-strike open interest** — Put/Call Wall and GEX use volume as proxy (labeled in output).
5. **broker-holding is HK-only** — US symbols return empty.
6. **Short data US/HK fields differ** — auto-detected by field presence.

For the full mapping (Futu↔Longbridge options, plus new modules CLI field map), see
[`references/capability-map.md`](references/capability-map.md) and
[`references/new-modules-map.md`](references/new-modules-map.md).

## Verification

All calculations have been cross-validated against theoretical constraints:
- Black-Scholes: Put-Call Parity holds (error < 3e-14), Gamma/Vega Call=Put symmetry exact
- Historical Volatility: matches `statistics.stdev` to floating-point precision
- P&L break-even: linear interpolation, verified against closed-form formulas

See [`references/calc-formulas.md`](references/calc-formulas.md) for the math.

## Trademark notice

**Longbridge** is a trademark of Longbridge Securities. **Futu** is a trademark of Futu Holdings. This project is an independent community tool, not affiliated with or endorsed by either. It calls the publicly documented Longbridge OpenAPI. See [LICENSE](LICENSE).

## License

[MIT](LICENSE)
