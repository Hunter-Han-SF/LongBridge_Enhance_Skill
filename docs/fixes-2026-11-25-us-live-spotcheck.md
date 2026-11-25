# 2026-11-25 美股盘前实盘抽检修复记录（0.6.5）

修复基准：`0abc48c`（main，0.6.4，PR #6 已合并）。

本轮针对美股盘前实盘抽检（`AAPL.US`、`MSFT.US`、`BRK.B.US`，CLI `0.27.1`）中复现的四组问题进行修复。

## 1. `get_trade_stats.py` 美股 50 档服务端截断导致 POC / VA 与多空方向失真

### 问题与实证
`longbridge trade-stats <SYM>` 的 `trades` 仅返回最高端的最多 50 个价位。港股最小变动价位大、50 档通常可覆盖；美股按 `$0.01`（含暗池半美分）分档，50 档只占 5 日总成交的极窄顶部：
- `AAPL.US`：`trades` 覆盖 `$354.195 ~ $359.98`（占 5 日总成交 `24,169,463` 股不足 1%），脚本算出假 `POC=354.24`、`VA=354.20~354.31`、主动买/卖比 `5.33`（而 `statistics` 全样本真实买/卖比 `3,516,984 / 4,169,746 = 0.84` 卖方占优）。
- `MSFT.US`：`trades` 覆盖 `$501.665 ~ $544.69`（合计 `6,313` 股，占 `statistics.total_amount=14,359,086` 股仅 **`0.044%`**），脚本算出假 `POC=501.67`、`VA=501.665~501.738`、主动买/卖比 `5.07`（全样本 `1,596,445 / 1,775,772 = 0.90` 卖方占优）。

### 修复
- 以 `sampled_volume / statistics.total_amount` 计算样本覆盖率，低于 `MIN_PROFILE_COVERAGE = 80%` 时 `profile_complete=False`：置空 `poc` / `vah` / `val`（退化局部样本极值保留为 `sample_poc`/`sample_vah`/`sample_val`），文本明确打印服务端截断警告而不输出全区间强弱结论。
- 主动买/卖量比优先采用 `statistics` 近 5 日全样本 `buy / sell`（`imbalance_basis="statistics_5d"`），局部样本比值保留为 `sample_buy_sell_imbalance`。
- 位置文案明确写「近5日均价」而非容易与实时现价混淆的「价格」。

## 2. 新挂牌周度期权链无 IV 导致 `get_option_volatility.py` 崩溃、`analyze_buy_sell.py` 丢信号

### 问题与实证
美股在提前约 6 周（~44 自然日）新挂牌周度链时，挂牌首日开盘前链上仅含行权价骨架、全链 `call_iv` / `put_iv` 为空（实测 `AAPL.US` 与 `MSFT.US` 的 `2027-01-08` 均为 29 行 0 IV，而相邻 `2026-12-31` 与 `2027-01-15` 均有完整 IV）。`nearest_tenor_expiry` 恰好命中 `2027-01-08` 导致：
- `get_option_volatility.py MSFT.US`（及 `AAPL.US`）直接报错退出：`2027-01-08 的 chain 中找不到 ATM IV`。
- `analyze_buy_sell.py MSFT.US` 的 `[期权定位]` 静默丢失 `IV/HV` 子项。

### 修复
- `common.py` 新增 `rank_tenor_expiries(expirations, calendar_days)` 按期限距离由近到远排序到期日。
- `get_option_volatility.py`（未显式指定 `--expiry` 时）与 `analyze_buy_sell._dim_options` 依次尝试距离最近的到期日，跳过尚无有效 ATM IV 的新链；同时 `get_option_volatility.py` 改用前复权 `get_kline_adjusted` 计算 HV、并用 `regular_session_price` 选链上 ATM（与上个常规时段 chain IV 对齐）。

## 3. 跨时段与美股节假日边界

- **美股节假日判定（`common.py`）**：新增 `us_market_holiday(d)`（按 NYSE/Nasdaq 规则覆盖元旦、MLK、总统日、Good Friday、阵亡将士纪念日、六月节、独立日、劳动节、感恩节、圣诞节），`_regular_session_state` 同步排除全日休市与 `us_early_close`（13:00 ET）半日市，避免周中休市日（如感恩节）误判盘中或丢弃节前盘后/夜盘报价；同时 `regular_session_price` 优先复用 `_LAST_PRICE_INFO` 已缓存的 `regular_price`，减少冗余 CLI 调用。
- **`get_vwap_analysis.py`**：新增 `--session intraday|all`，在盘前/未开盘阶段检测到返回分钟线属于上一交易日时，将 `date` 标注为实际交易日、`is_prior_session=True`，并提示查看实时盘前/盘后/夜盘分时可加 `--session all`。
- **`calc_anomaly_score.py`**：`_get_quote` 改接 `get_underlying_quote` + `latest_underlying_price`，盘前/盘后/夜盘按延长时段报价与 `prev_close` 计算涨跌幅并标注来源（复测 `MSFT.US` 盘前 `-2.46%` 正确归为 `下跌` 而非昨日常规时段的 `上涨`）。
- **`calc_expected_move.py` 与 `get_iv_term_structure.py`**：按 `regular_session_price` 从常规时段链上选取 ATM 与跨式权利金（解决 `MSFT.US` 盘前 483.91 误选 485 实值 Call 导致 0DTE 跨式权利金虚高至 `$11.83 / ±2.44%` 的失真）。

## 4. 代码细节与实战稳健性

- **多点号/单字母美股代码**：`check_entry_rules.py`、`get_valuation_percentile.py`、`analyze_iv_crush.py`、`get_dividend_quality.py` 统一改用 `common.parse_underlying`（替代 `symbol.split(".")[0]` / `.endswith(...)`），正确区分 `BRK.A.US` / `BRK.B.US` 及单字母 `A.US`。
- **入场规则窄止损与盘前跌破告警（`check_entry_rules.py`）**：当延长时段最新价已跌破建议止损位（如 `MSFT.US` 盘前 `483.92` < 建议止损 `490.29`）时在 `price_note` 醒目告警；当止损距离小于 `0.5 × ATR` 时在 `D5`/`U4` 证据中附加噪音扫损提示；新增可选 `--min-stop-pct` 参数。
- **仪表盘可读性（`analyze_buy_sell.py`）**：未核实货币单位的大单净额改用千分位格式化、`55/58 家看多` 取整并去除重复表情、维度标签去除易误解的 `%`（总权重 90）、`_dim_options` 复用外层现价。
- **选股器数量限制（`run_screener.py`）**：`common.screener_filter` 与 `run_screener.py` 新增 `--count` 参数（支持 `--filter ... --count N` 与 `--run ID --count N`）。

## 验证

- 新增 `tests/test_fixes_v065.py`，并更新 `tests/test_scripts_v04.py`、`tests/test_fixes_v062.py` 以对齐新契约。
- 全量离线回归测试、Python 3.8 语法检查及 `AAPL.US` / `MSFT.US` 实盘复检见本次交付报告。
