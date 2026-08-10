# LongBridge Enhance Skill

**[English](README.md)** | [中文](README.zh-CN.md)

> Community-developed options analytics enhancement for the [Longbridge OpenAPI](https://open.longbridge.com).
> Provides Black-Scholes Greeks, historical volatility, IV Rank/Percentile, volatility smile, put-call ratio, strategy P&L, and more — computed locally from Longbridge CLI data.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What this is

The official `longbridge-derivatives` skill gives you **raw option chain data** (strikes, IV, prices) via the Longbridge CLI. This enhancement skill adds the **compute layer on top** — Black-Scholes pricing, Greeks, volatility analysis, and strategy P&L that the raw CLI doesn't provide natively.

It was built to replicate the option analytics capabilities of similar brokers (e.g. Futu's OpenAPI option suite), adapted to what Longbridge's API exposes.

## Features

### 🟢 Native data (wrapped from Longbridge CLI)
- **Option expiration dates** — list all tradable expiries
- **Option chain** — strikes with IV / last price / volume per expiry
- **Put/Call ratio** — real-time snapshot + daily time series (with open interest)
- **OCC symbol resolver** — construct & validate OCC option codes

### 🟡 Computed analytics (the core value)
- **Single-contract Greeks** — Delta / Gamma / Theta / Vega / Rho via Black-Scholes
- **IV vs HV** — implied vol (from chain) vs historical vol (from K-line), with rich/cheap judgment
- **Volatility smile & skew** — per-strike IV curve + put skew (downside fear indicator)
- **IV Rank & IV Percentile** — via local accumulation (see Limitations below)
- **Exercise probability** — BS closed-form N(d2) + |delta| approximation
- **Portfolio Greeks** — multi-leg weighted Greeks with BUY/SELL sign handling
- **Expiration P&L analysis** — break-even points (linear interpolation), max profit/loss
- **Strategy leg generator** — 8 standard strategies (Straddle, Strangle, Spreads, Butterfly, Collar, Covered Call, CSP)

## Requirements

- **Longbridge CLI** installed and authenticated (`longbridge auth login`)
- **Python 3.8+** (no third-party packages — pure standard library)
- Longbridge account with **OPRA options market data** permission

## Installation

### Option A: As a ZCode / Claude Code skill

Copy this folder to your skills directory:

```bash
# ZCode
cp -r longbridge-derivatives-pro ~/.zcode/skills/

# Claude Code
cp -r longbridge-derivatives-pro ~/.claude/skills/
```

Verify the environment:

```bash
python scripts/check_env.py
```

### Option B: Standalone scripts

Clone and run directly — the scripts work anywhere with Python + Longbridge CLI:

```bash
git clone https://github.com/Hunter-Han-SF/LongBridge_Enhance_Skill.git
cd LongBridge_Enhance_Skill
python scripts/check_env.py
```

## Quick start

```bash
# Option chain for AAPL
python scripts/quote/get_option_chain.py AAPL.US --date 2026-09-18

# Is AAPL's IV cheap or expensive? (IV vs HV)
python scripts/quote/get_option_volatility.py AAPL.US

# Greeks for a specific contract (Black-Scholes computed)
python scripts/quote/get_option_quote.py AAPL.US 2026-08-14 315 CALL

# Analyze a Bull Call Spread P&L
python scripts/quote/get_option_strategy.py AAPL.US 2026-08-14 BULL_CALL_SPREAD
# ...then pipe the legs JSON into:
python scripts/quote/calc_option_pnl.py '<legs-json>'
```

See [`SKILL.md`](SKILL.md) for the full command reference.

## Known limitations

These are **data-source limitations** of the Longbridge API, not bugs:

1. **Single-contract `option quote` returns empty** — The CLI's `option quote <OCC>` currently returns `[]` for all contracts (reason unclear despite OPRA permission). Greeks are therefore computed via Black-Scholes using IV from the chain, not fetched natively.

2. **No historical IV** — `option chain` only returns real-time data; you cannot query a past date. IV Rank / IV Percentile use a **local accumulation** model: run `get_iv_history.py` daily to build a series in `~/.lbr_iv_history/`.

3. **US options only (OPRA)** — HK / A-share option data returns empty per Longbridge's coverage.

4. **Put/Call ratio is US-only** — `option volume daily` does not support HK.

For the full Futu ↔ Longbridge capability mapping (including what's **not** implementable — unusual options activity, 0DTE screeners, etc.), see [`references/capability-map.md`](references/capability-map.md).

## Not included (and why)

Some capabilities of similar brokers' option APIs are **fundamentally impossible** with Longbridge's data:

- ❌ Unusual options activity / sweep / block detection (requires per-trade OPRA tick stream with exchange flags)
- ❌ 0DTE screeners (depends on the above)
- ❌ Earnings IV Crush forecasts (requires historical IV + earnings date correlation server-side)
- ❌ Seller strategy screeners with annualized return (requires full-market scan)

These are proprietary server-side data products, not generic API outputs.

## Verification

All calculations have been cross-validated against theoretical constraints:
- Black-Scholes: Put-Call Parity holds (error < 3e-14), Gamma/Vega Call=Put symmetry exact, Delta(Call) - Delta(Put) = 1
- Historical Volatility: matches `statistics.stdev` to floating-point precision
- P&L break-even: linear interpolation, verified against closed-form formulas

See [`references/calc-formulas.md`](references/calc-formulas.md) for the math.

## Trademark notice

**Longbridge** is a trademark of Longbridge Securities. **Futu** is a trademark of Futu Holdings. This project is an independent community tool, not affiliated with or endorsed by either. It calls the publicly documented Longbridge OpenAPI. See [LICENSE](LICENSE).

## License

[MIT](LICENSE)
