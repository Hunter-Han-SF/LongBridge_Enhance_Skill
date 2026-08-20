# LongBridge Enhance Skill (longbridge-pro)

**[English](README.md)** | [中文](README.zh-CN.md)

> Community-developed multi-dimensional analytics enhancement for the [Longbridge OpenAPI](https://open.longbridge.com).
> Nine modules: ① Options analytics (BS Greeks, IV/HV, vol smile, P/C ratio, P&L, Put/Call Wall, GEX, IV Crush,
> Expected Move, risk reversal, IV term structure, Max Pain)
> ② Anomaly tracking ③ Capital flow / main force ④ Event calendar ⑤ Market sentiment
> ⑥ Technicals (MA/MACD/RSI/KDJ/BOLL/ATR/OBV + composite score + relative strength/Beta)
> ⑦ Fundamentals (valuation percentile / analyst consensus / financial health / dividend quality)
> ⑧ Intraday microstructure (VWAP / order-book imbalance / tick order flow) ⑨ Buy/sell decision dashboard
> — all computed locally from Longbridge CLI data.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What this is

The official `longbridge` skill series gives you **raw data** (option chains, quotes, fundamentals) via the Longbridge CLI. This enhancement skill adds the **compute and fusion layer on top** — Black-Scholes pricing, Greeks, volatility analysis, strategy P&L, anomaly scoring, capital-flow analytics, a full technical-indicator suite, valuation percentiles, analyst consensus, intraday VWAP/order-book/tick analytics, and a six-dimension buy/sell decision dashboard — none of which the raw CLI provides.

## Features

### 🟢 Module ①: Options analytics (US OPRA)
- **Option chain / expirations / P-C ratio / OCC resolver** — native data wrapped
- **Single-contract Greeks** — Delta / Gamma / Theta / Vega / Rho via Black-Scholes
- **IV vs HV** — implied vol (from chain) vs historical vol (from K-line)
- **Volatility smile & skew** — per-strike IV curve + put skew
- **IV Rank & IV Percentile** — via local accumulation
- **Exercise probability / Portfolio Greeks / Expiration P&L / 8 strategy legs** (incl. STOCK legs for collar/covered-call)
- **Put/Call Wall** — largest-volume strikes as support/resistance
- **Gamma Exposure (GEX)** — dealer hedging pressure + zero-gamma flip point
- **Earnings IV Crush** — pre/post-earnings IV change with earnings calendar
- **Expected Move** — ATM-straddle implied move (1σ range) per expiry
- **IV term structure** — contango/backwardation + event-premium expiry detection
- **25Δ Risk Reversal** — standardized skew: IV(25Δ call) − IV(25Δ put)
- **Max Pain** — expiry "gravity" strike (volume-proxy, labeled)

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

### 📈 Module ⑥: Technicals
- **Full indicator suite** — MA/EMA/MACD/RSI(Wilder)/KDJ/BOLL/ATR/OBV/MFI/volume ratio/ROC/Williams %R/CCI/52-week position/max drawdown, on forward-adjusted K-lines
- **Signal detection** — MA alignment, MA/MACD/KDJ golden & death crosses, overbought/oversold, 20-day breakouts, 250-day line
- **Composite score** — 0-100 across trend/momentum/volume/position dimensions
- **Relative strength + Beta** — 1-week to 1-year out/under-performance vs benchmark (default SPY / 2800.HK / 510300.SH)

### 🏦 Module ⑦: Fundamentals
- **Valuation percentile** — current PE/PB vs 5-year history percentile + industry peer comparison
- **Analyst consensus** — rating distribution, target-price range vs spot, EPS forecast dispersion
- **Financial health** — key line items from all three statements with traffic-light ratings (growth/profitability/leverage/cash flow)
- **Dividend quality** — TTM yield, consecutive years, complete-year growth, frequency stability

### ⚡ Module ⑧: Intraday microstructure
- **VWAP analysis** — price vs session VWAP deviation + time-above-VWAP ratio
- **Order-book pressure** — L2 depth imbalance, bid/ask volume ratio, largest walls
- **Tick order flow** — active buy/sell ratio (volume & notional), large-trade detection, closing mood

### 🎯 Module ⑨: Buy/sell decision dashboard
- **Six-dimension aggregate** — technicals 30% + valuation 15% + capital flow 20% + options 10% + analysts 15% + event risk 10%
- Outputs bull vs bear factor lists and a composite signal; failed dimensions auto-de-weight; non-US symbols get a neutral options score

## Requirements

- **Longbridge CLI** installed and authenticated (`longbridge auth login`)
- **Python 3.8+** (no third-party packages — pure standard library)
- Options module needs **OPRA options market data** permission (all other modules only need stock quotes)

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

# === Technicals & fundamentals & intraday ===
python scripts/technical/calc_indicators.py AAPL.US             # full indicator suite + signals
python scripts/fundamental/get_valuation_percentile.py AAPL.US  # valuation percentile
python scripts/intraday/get_vwap_analysis.py AAPL.US            # VWAP

# === One-click daily briefing / buy-sell dashboard ===
python scripts/sentiment/daily_briefing.py --market US
python scripts/decision/analyze_buy_sell.py AAPL.US             # six-dimension bull/bear view
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
7. **Depth/trades are snapshots** — after-hours shows the last snapshot; tick-flow sample size depends on session.
8. **Valuation history often PE-only for US** — some symbols also have PB/PS; scripts handle whatever is returned.
9. **Technical scoring weights & traffic-light thresholds are design choices** — adjustable, labeled in output.

For the full mapping (Futu↔Longbridge options, plus new modules CLI field map), see
[`references/capability-map.md`](references/capability-map.md) and
[`references/new-modules-map.md`](references/new-modules-map.md).

## Verification

All calculations have been cross-validated against theoretical constraints:
- Black-Scholes: Put-Call Parity holds (error < 3e-14), Gamma/Vega Call=Put symmetry exact, theta/vega/rho match finite differences
- Historical Volatility: matches `statistics.stdev` to floating-point precision
- P&L break-even: linear interpolation, verified against closed-form formulas
- Technical indicators: boundary values (monotonic rise RSI=100, symmetric Wilder RSI=50), Bollinger vs `statistics.pstdev`, Beta(2×market)=2

See [`references/calc-formulas.md`](references/calc-formulas.md) for the math.

## Trademark notice

**Longbridge** is a trademark of Longbridge Securities. **Futu** is a trademark of Futu Holdings. This project is an independent community tool, not affiliated with or endorsed by either. It calls the publicly documented Longbridge OpenAPI. See [LICENSE](LICENSE).

## License

[MIT](LICENSE)
