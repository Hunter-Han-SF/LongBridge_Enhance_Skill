# LongBridge Enhance Skill (longbridge-pro) · 0.6.1

**[English](README.md)** | [中文](README.zh-CN.md)

> Community-developed multi-dimensional analytics enhancement for the [Longbridge OpenAPI](https://open.longbridge.com).
> Ten modules: ① Options analytics (native Greeks, IV/HV, vol smile, P/C ratio, P&L, Put/Call Wall, GEX, IV Crush,
> Expected Move, risk reversal, IV term structure, Max Pain, OI distribution, Gamma Profile + HK warrants)
> ② Anomaly tracking (+ index constituents / sector rotation / A-H premium) ③ Capital flow / main force (+ HK broker queue)
> ④ Event calendar (earnings/dividends/splits/IPO/macro/market holidays/new-listing profiles) ⑤ Market sentiment (+ macro indicator history)
> ⑥ Technicals (MA/MACD/RSI/KDJ/BOLL/ATR/OBV + composite score + relative strength/Beta + server-side quant)
> ⑦ Fundamentals (valuation percentile / analyst consensus / financial health / dividend quality / multi-stock compare /
> business segments / industry rank / consensus detail / corp actions / operating reviews / company profiles
> + insider trades / 13F institutional holdings / fund holders / shareholders)
> ⑧ Intraday microstructure (VWAP / order-book imbalance / tick order flow / volume profile)
> ⑨ Buy/sell decisions (dashboard + 28-rule entry discipline checker) ⑩ Stock screener (preset strategies / custom filters)
> — all computed locally from Longbridge CLI data, with an offline regression suite.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What this is

The official `longbridge` skill series gives you **raw data** (option chains, quotes, fundamentals) via the Longbridge CLI. This enhancement skill adds the **compute and fusion layer on top** — Black-Scholes pricing, Greeks, volatility analysis, strategy P&L, anomaly scoring, capital-flow analytics, a full technical-indicator suite, valuation percentiles, analyst consensus, intraday VWAP/order-book/tick analytics, and a five-directional-input dashboard with separate event risk — none of which the raw CLI provides.

## Features

### 🟢 Module ①: Options analytics (US OPRA)
- **Option chain / expirations / P-C ratio / OCC resolver** — native data wrapped
- **Single-contract quote** — native server Greeks first (calc-index, incl. OI), Black-Scholes fallback
- **IV vs HV** — implied vol (from chain) vs historical vol (from K-line)
- **Volatility smile & skew** — per-strike IV curve + put skew
- **IV Rank & IV Percentile** — from locally collected constant 30-day ATM IV. Rank and percentile require a successful current capture and at least 20 comparable observations by default. Legacy records are retained and excluded
- **Exercise probability / Portfolio Greeks / Expiration P&L / 8 strategy legs** (incl. STOCK legs for collar/covered-call)
- **Put/Call Wall** — real-OI walls (calc-index, volume fallback) as support/resistance
- **Gamma Exposure (GEX)** — OI-weighted gamma and interpolated zero crossings under a Call-positive, Put-negative positioning assumption. OI provides no observed dealer net position
- **Gamma Profile (flagship)** — multi-expiry (60-day) aggregate GEX surface + interpolated gamma flip + OI-kernel-density fine-grained S/R
- **Options OI distribution** — per-strike real OI + P/C OI ratio (positioning) + OI walls
- **IV decline and earnings context** — current constant 30-day IV, the available earnings calendar, and adjacent-calendar-day IV drops over 20%. Historical drops are not matched to earnings events
- **Expected Move** — ATM straddle premium range around spot, expiry break-even prices at strike ± premium, and a separate IV model scale of `spot × IV × √T`. The premium range carries no fixed coverage probability
- **IV term structure** — contango/backwardation + event-premium expiry detection
- **25Δ Risk Reversal** — standardized skew: IV(25Δ call) − IV(25Δ put)
- **Max Pain** — strike that minimizes aggregate modeled expiry intrinsic payout, weighted by OI or a labeled volume fallback. It provides no price-attraction forecast
- **HK warrants** (HK only) — underlying's full warrant list (leverage/expiry stats) + contract quotes + issuers; direction taken from quote (list `type` unreliable)

### 🔵 Module ②: Anomaly tracking
- **Anomaly signals** — block trades, limit-up/down, with bull/bear emotion tags
- **Top movers** — stocks beating 20-day volatility bands, with correlated news
- **Anomaly composite score** — single-symbol 0-100 score fusing signals + capital flow + change + movers
- **Index / ETF constituents** — sortable by change/inflow/turnover, sector-rotation monitoring
- **A/H premium** — dual-listed premium K-line/intraday + z-score + convergence trend

### 💰 Module ③: Capital flow / main force
- **Capital distribution** — large/medium/small order inflow/outflow, net and minute observations. Values retain source units by default. Once the feed convention is verified, set `LBR_CAPITAL_SCALE` to a positive multiplier and `LBR_CAPITAL_FLOW_MODE` to `cumulative` or `incremental` (default `unknown`)
- **HK broker holdings** — top-10 buy/sell brokers, full detail, single-broker history (HK only)
- **HK broker queue** — which institution is queuing at each price level (names resolved; support/pressure detection)
- **Short selling** — daily short-volume ratio + open interest (US days-to-cover / HK cost)

### 📅 Module ④: Event calendar
- **Earnings calendar** — estimated/actual EPS, published vs TBD
- **Dividend calendar** — amount, type (regular/special), payment date
- **Split calendar** — ratio auto-parsed ("5 shares merged into 1" → 5→1 reverse split)
- **IPO suite** — listing calendar / stage lists (subscription/grey-market/listed) / IPO detail (cornerstone investors + quotas)
- **Macro release calendar + market-holiday calendar**

### 🌡️ Module ⑤: Market sentiment
- **Market temperature** — 0-100 index + valuation/sentiment sub-scores + history
- **Heat rankings** — total heat / rising / trading / discussion / watchlist across markets
- **Daily briefing** — one-click aggregate (temp + heat top5 + movers top5 + anomaly stats + SPY P/C)
- **Macro indicators** — CPI/PMI/rates history + beat/miss statistics

### 📈 Module ⑥: Technicals
- **Full indicator suite** — MA/EMA/MACD/RSI(Wilder)/KDJ/BOLL/ATR/OBV/MFI/volume ratio/ROC/Williams %R/CCI/52-week position/max drawdown, on forward-adjusted K-lines
- **Signal detection** — MA alignment, MA/MACD/KDJ golden & death crosses, overbought/oversold, 20-day breakouts, 250-day line
- **Composite score** — 0-100 across trend/momentum/volume/position dimensions
- **Relative strength + Beta** — 1-week to 1-year out/under-performance vs benchmark (default SPY / 2800.HK / 510300.SH)
- **Volume ratio** — latest bar volume divided by the prior five-bar mean. Missing volumes remain unavailable.
- **Server-side quant indicators & backtest** — pine presets (EMA/RSI/MACD + EMA-cross backtest). `--cross-check` explicitly skips comparison in text and JSON because the server summary lacks verifiable bar times, adjustment and warm-up inputs

### 🏦 Module ⑦: Fundamentals
- **Valuation percentile** — current PE/PB vs 5-year history percentile + industry peer comparison
- **Analyst consensus** — rating distribution, target-price range vs spot, EPS forecast dispersion
- **Financial health** — key line items from all three statements with traffic-light ratings (growth/profitability/leverage/cash flow). Cross-statement ratios require compatible reporting periods, and the verdict stays unassessed when key metrics are unavailable
- **Dividend quality** — Trailing-year ex-dates through the instrument's market date. Yield requires matching dividend and quote currencies. Growth compares received same-currency records from the two latest ended calendar years; an ended year does not prove feed completeness
- **Multi-stock compare** — up to 5 symbols across PE/PB/PS/ROE/margins/yield, with in-group rankings
- **Business segments** — revenue split + concentration (CR1/CR2)
- **Industry rank + hierarchy tree + valuation distribution** — sector performance, leading stocks, sub-industries, in-industry valuation percentile
- **Consensus detail** — line-item estimates vs actuals (beat/miss labeled)
- **Corporate actions / HK operating reviews / company profiles + executives**

### 🧠 Module ⑦ signal sources (institutions & insiders)
- **Insider trades** (SEC Form 4, US only) — P/S purchase/sale totals, with grants, exercises and issuer dispositions listed separately. Net value describes transactions without inferring intent
- **13F institutional holdings** — AUM rankings / per-firm holdings / quarter-over-quarter changes (new/added/reduced/exited)
- **Fund holders / shareholders** — who is overweight, increase/decrease direction

### ⚡ Module ⑧: Intraday microstructure
- **VWAP analysis** — price vs session VWAP deviation, the share of valid observations above VWAP, and input coverage. Thirty-minute trends require the matching timestamp
- **Order-book pressure** — L2 depth imbalance, bid/ask volume ratio, largest walls
- **Tick order flow** — uptick/downtick estimates for volume and notional, with unclassified trades shown separately. Price direction does not identify the trade aggressor
- **Volume Profile** (5-day) — point of control (highest-volume price level) + 70% Value Area (VAH/VAL) + position judgment

### 🎯 Module ⑨: Buy/sell decision dashboard + entry discipline checker
- **Directional score** — technical 30, valuation 15, capital flow 20, US options 10, analysts 15. A signal requires technicals and at least 60 points of observed weight.
- **Event risk** — earnings within seven days can reduce a bullish score by up to seven points, stopping at neutral. Event risk is separate from directional coverage.
- Insider/13F/fund-holder signals available as additional independent context
- **Entry discipline checker (28 rules)** — `check_entry_rules.py` encodes a personal trading
  checklist: 12 no-buy rules in downtrends (D1–D12), 6 no-buy rules in uptrends (U1–U6),
  and 10 candidate setup checks (B0–B9, with B0 as a minimum 1:1 reward/risk gate).
  Every rule reports triggered / clear / needs-manual with evidence (new lows, volume dry-up,
  RSI(6) extremes & divergence, Fibonacci 61.8%, trendline/neckline breaks, S/R clustering,
  engulfing/hammer/W-bottom/flag detection, MA5/MA10 first pullback, earnings proximity,
  last 30 minutes before the open, heat-rank hits, stop distance vs tolerance). Manual items
  (recent stop-out, familiarity, sector ranking …) resolve via CLI flags. A pending required item, unavailable live price or volume, or an unconfirmed B0 gate prevents a pass. Use `--target-price` to supply the B0 target.

### 🔍 Module ⑩: Stock screener
- **Preset strategies** — 17 official strategies (low valuation / high growth / today's gainers …) run by ID
- **Custom filters** — `pettm:10:50 roe:5:` style conditions (25+ indicator keys)
- **Screen → score workflow** — pipe screened names straight into the directional dashboard with separate event risk

## Requirements

- **Longbridge CLI** installed and authenticated (`longbridge auth login`)
- **Python 3.8+ syntax target** (pure standard library). The 0.6.0 suite was run on Python 3.13.15; a Python 3.8 interpreter was not exercised
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

Commands with an explicit expiry or strike elsewhere in the documentation are syntax examples. Use `get_option_expiration.py` and the current chain to select a listed contract; commands below omit optional expiries so they select a remaining expiry automatically.

```bash
# === Options ===
python scripts/quote/get_option_volatility.py AAPL.US        # IV vs HV
python scripts/quote/get_put_call_wall.py AAPL.US             # OI concentration levels
python scripts/quote/get_warrant.py 700.HK --enrich 20       # HK warrants

# === Anomaly & capital flow ===
python scripts/market/get_top_movers.py --market US          # movers + news
python scripts/market/get_constituent.py HSI.HK --sort inflow  # index constituents
python scripts/flow/get_capital_flow.py AAPL.US --flow       # minute capital flow
python scripts/flow/get_broker_holding.py 700.HK --detail    # HK broker holdings
python scripts/flow/get_broker_queue.py 700.HK               # HK broker queue

# === Screening ===
python scripts/screener/run_screener.py --filter pettm:5:30 --filter roe:10: --market HK

# === Calendar & sentiment ===
python scripts/calendar/get_earnings_calendar.py --market US
python scripts/sentiment/get_market_temp.py US
python scripts/sentiment/get_macro_data.py --keyword CPI --country US  # macro indicators

# === Technicals & fundamentals & intraday ===
python scripts/technical/calc_indicators.py AAPL.US             # full indicator suite + signals
python scripts/fundamental/get_valuation_percentile.py AAPL.US  # valuation percentile
python scripts/fundamental/compare_stocks.py AAPL.US MSFT.US NVDA.US  # multi-stock compare
python scripts/fundamental/get_insider_trades.py TSLA.US        # insider trades
python scripts/intraday/get_vwap_analysis.py AAPL.US            # VWAP
python scripts/intraday/get_trade_stats.py 700.HK               # volume profile (POC/VA)

# === One-click daily briefing / buy-sell dashboard / entry discipline ===
python scripts/sentiment/daily_briefing.py --market US
python scripts/decision/analyze_buy_sell.py AAPL.US             # directional inputs + separate event risk
python scripts/decision/check_entry_rules.py AAPL.US            # 28-rule entry checklist
```

Run the offline regression suite (mocked CLI):

```bash
python -m unittest discover -s tests -v
```

See [`SKILL.md`](SKILL.md) for the full command reference and [the 0.6.0 audit record](docs/audit-fixes-2026-11-03.md) for all 27 findings, compatibility changes and validation evidence.

## Known limitations

These are recorded interface observations and model limitations. The 0.6.0 audit uses offline fixtures; it does not certify the current server contract.

1. **Single-contract `option quote` returned empty in earlier samples** — current wrappers prefer native Greeks via `calc-index`, then fall back to Black-Scholes using chain IV.
2. **No historical IV** — IV Rank/Percentile use **local accumulation** (`get_iv_history.py` daily).
3. **US options only (OPRA)** — HK / A-share options return empty (HK derivatives covered via `warrant`).
4. **Per-strike OI — solved** — `calc-index` provides real OI + native Greeks per contract; Wall/GEX/MaxPain/P-C OI now use real OI (volume only as fallback).
5. **broker-holding / brokers queue are HK-only** — US symbols return empty.
6. **Short data US/HK fields differ** — auto-detected by field presence.
7. **Depth/trades are snapshots** — after-hours shows the last snapshot; tick-flow sample size depends on session.
8. **Valuation history often PE-only for US** — some symbols also have PB/PS; scripts handle whatever is returned.
9. **Technical scoring weights & traffic-light thresholds are design choices** — adjustable, labeled in output.
10. **warrant list `type` field unreliable** — direction taken from quote's type (Call/Bull = call, Bear/Put = put).
11. **`quant run` Navi path server error (observed 2026-08-21) — solved via Pine** — even official Navi doc examples return internal server error, but `--language pine` works; all built-in presets now use pine. Indicator series values are parsed from the pretty table (JSON mode's events_json lacks plot values); backtests use report_json.
12. **macrodata doc example codes are stale** — fetch real indicator codes from the list mode (`--keyword`) first.

For the full mapping (Futu↔Longbridge options, plus new modules CLI field map), see
[`references/capability-map.md`](references/capability-map.md) and
[`references/new-modules-map.md`](references/new-modules-map.md).

## Verification

Offline regression tests cover selected formula and input edge cases. Directional weights and setup rules are heuristics without out-of-sample return validation.
- Black-Scholes: tested positive-input cases satisfy put-call parity and finite-difference sensitivities within floating-point tolerances; deterministic limits and undefined payoff kinks have separate regressions
- Historical Volatility: matches `statistics.stdev` to floating-point precision
- P&L break-even: piecewise expiry payoff and analytical break-even roots
- Technical indicators: boundary values (monotonic rise RSI=100, symmetric Wilder RSI=50), Bollinger vs `statistics.pstdev`, Beta(2×market)=2

See [`references/calc-formulas.md`](references/calc-formulas.md) for the math.

## Trademark notice

**Longbridge** is a trademark of Longbridge Securities. **Futu** is a trademark of Futu Holdings. This project is an independent community tool, not affiliated with or endorsed by either. It calls the publicly documented Longbridge OpenAPI. See [LICENSE](LICENSE).

## License

[MIT](LICENSE)
