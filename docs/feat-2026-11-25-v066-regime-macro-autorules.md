# 2026-11-25 v0.6.6 更新记录（PR-1：大盘 Regime + 3 星宏观催化 + 军规半自动项打通 + CLI 0.32.0 兼容）

开发基准：`7a7e33f`（main，0.6.5，PR #7 已合并）；CLI 实测版本：`longbridge 0.32.0`。

## 1. CLI `0.32.0` 升级兼容与底层加固（`scripts/common.py`）

- **批量查询部分无效代码容错**：`longbridge >= 0.31.1` 在批量 `quote` / `calc-index` 中只要混入任一无效代码，就会返回非 `0` 退出码并在 `stdout` 打印其余有效标的数组。`run_cli()` 新增 `allow_partial=False` 参数（在保留 auth 检测与限频重试的前提下，批量场景启用 `allow_partial=True` 解析合法非空 JSON 数组），覆盖 `get_option_contract_metrics()` 与新增的 `get_batch_quotes()`。
- **公共封装补全**：
  - `get_batch_quotes(symbols)`：单次 CLI 批量拉取多标的报价（含延长时段与涨跌幅）。
  - `get_finance_calendar(..., star=None)`：支持传递 `--star` 过滤宏观日历重要性。
  - `get_industry_rank(market, count=200)`：默认拉取 `200` 条覆盖美股全部 140 个细分行业（旧实现默认 20 条截断了主流科技行业）。
  - `get_symbol_news(symbol, count=5)`：封装个股最新新闻只读接口。
  - 修复 `_regular_session_state` 与 `latest_underlying_price` 对传入 UTC / 异时区 aware `now` 时未换算至美东当地墙钟时间的问题。

## 2. 宏观日历字段修复与 Tier-1 分级（`scripts/calendar/get_macro_calendar.py`）

- 修复原实现读取不存在的 `ext.importance` 导致重要性星级为空、及未拼接 `bucket["date"]` 导致时间缺日期的问题，改为读取顶层 `star`（1~3 星）与 `bucket["date"] + info["date"]`（并用 `release_ts` 校准）。
- 新增 `classify_macro_tier()` 与 `--star` / `--tier1` 参数，在 3 星宏观事件中识别 **Tier-1 核心催化**（FOMC 联邦基金利率、CPI / 核心 CPI、PCE / 核心 PCE、非农就业、失业率、初请失业金、GDP）。

## 3. 大盘环境引擎及三端接入（`scripts/market/get_market_regime.py` + 决策/简报联动）

- 新增 `scripts/market/get_market_regime.py`（支持美股 `.VIX.US` + `SPY.US`/`QQQ.US` 盘前/夜盘跳空与 `MA20/50/200` + 未来 24-48h Tier-1 宏观催化；港/A 股采用 `2800.HK`/`510300.SH` + `market-temp` + 3 星宏观），输出 `risk_on` / `neutral` / `caution` / `risk_off` 四档环境状态。
- **`analyze_buy_sell.py`**：默认在事件风险与 JSON `market_regime` 中联动大盘环境与 24h 内 Tier-1 宏观，逆风/避险时最多将多头方向分额外削减（与财报叠加封顶 `MAX_EVENT_PENALTY = 15`，绝不将偏空得分压更低），支持 `--no-regime` 跳过。
- **`daily_briefing.py`**：新增 `🧭 大盘环境与重磅宏观` 章节与 `--no-regime`。

## 4. 入场纪律检查器半自动项打通（`scripts/decision/check_entry_rules.py`）

- **B8 板块共振全自动映射**：通过 `get_institution_rating()` 提取 `analyst.industry_name`，与拉全 140 个细分行业的 `get_industry_rank(count=200)` 精确匹配，不再限于行业领涨股。
- **D11 盘前/盘后消息异动三区自动分诊**：常规时段或延长时段涨跌幅处平稳阈值内自动判 `clear`；非财报窗口出现大幅跳空时拉取最新新闻标题自动判 `triggered`；中间区域或财报窗口保留并附带涨跌幅与新闻标题提示 `manual`。
- **D6 昨日板块跌幅前 10% 智能排雷**：上一完整日K未显著收跌（`≥ -0.3%`）、或跑赢所属行业、或 `valuation` 同行中有 `≥30%` 个股表现更弱时自动放行 `clear`。
- **大盘环境展示与 `--strict-regime`**：默认顶部展示 `🧭 大盘环境`，开启 `--strict-regime` 后当处于 `risk_off` 或 24h 内有 Tier-1 宏观催化时直接阻断买点结论。

## 验证

- 新增 `tests/test_fixes_v066.py` 并更新 `tests/test_entry_rules_v050.py`、`tests/test_dirty_fuzz_v056.py`。
- 全量离线回归测试、Python 3.8 AST 检查、`SKILL.md` frontmatter 长度校验及 `longbridge 0.32.0` 美股实盘复检见 PR 说明。
