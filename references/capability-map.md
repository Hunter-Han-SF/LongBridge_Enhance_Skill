# Futu ↔ Longbridge 期权能力映射表

本 skill 复刻 Futu 期权能力的 **A 档(原生)+ B 档(计算)**,**不实现 C 档**(Longbridge 无对应数据源)。

## 三档说明

| 档位 | 含义 | 实现方式 |
|---|---|---|
| 🟢 A 档 | Longbridge CLI 原生支持,直接包一层 | 调 `longbridge option/quote/kline` |
| 🟡 B 档 | Longbridge 不直接提供,但可用现有数据 + 数学计算得出 | CLI 拉数据 + Python 算 |
| 🔴 C 档 | Longbridge 根本没有数据源,无法实现 | 明确标注不支持 |

---

## 基础期权能力映射（后续扩展见 new-modules-map.md）

### 🟢 A 档:原生(5 个脚本)

| 本 skill 脚本 | CLI 命令 | 对应 Futu | 说明 |
|---|---|---|---|
| `get_option_expiration.py` | `option chain <UL>` | `get_option_expiration_date` | 到期日列表 |
| `get_option_chain.py` | `option chain <UL> --date` | `get_option_chain` | 某到期日的行权价 + IV + 价格 |
| `get_option_volume.py` | `option volume` / `volume daily` | `get_option_market_statistic` | 实时/每日 Call-Put 成交量 + **P/C 比率**(原生!) |
| `resolve_option_code.py` | `build_occ_code` + chain 验证 | `resolve_option_code` | 构造 OCC 代码(Longbridge chain 不返回 symbol) |
| `get_option_quote.py`(原生部分) | `calc-index <Longbridge合约代码>` | `get_option_quote` | 原生 Greeks/OI 优先，缺失才回退 BS |

### 🟡 B 档:计算(10 个脚本)

| 本 skill 脚本 | 数据源 | 对应 Futu | 计算方法 |
|---|---|---|---|
| `get_option_volatility.py` | chain IV + kline | `get_option_volatility` | HV = std(ln收益)×√252;IV/HV 比率(0.6.2 起期限对齐:IV 取期限最接近 HV 窗口的到期日) |
| `get_vol_smile.py` | chain 各 strike IV | `get_option_volatility`(扩展) | 提取 smile + put skew |
| `get_option_quote.py`(BS 部分) | chain IV | `get_option_quote` | BS 公式算 delta/gamma/theta/vega/rho |
| `calc_option_greeks.py` | 各腿原生 Greeks / chain IV 回退 | `get_option_strategy_analysis`(Greeks) | 同标的，按方向×数量×100加权 |
| `calc_exercise_prob.py` | chain IV + 现价 | `get_option_exercise_probability` | BS N(d2) / |delta| 近似 |
| `calc_option_pnl.py` | chain last price | `get_option_strategy_analysis`(损益) | 到期损益曲线/盈亏平衡/最大盈亏 |
| `get_option_strategy.py` | chain + 现价 | `get_option_strategy` | 生成 11 种买方/卖方/中性策略腿（支持 `--delta`、`--width`、`--with-pnl`、`--check-liquidity`） |
| `get_iv_history.py` | 每日累积 + 问股自动补录 | `get_option_underlying_his_volatility` | **本地累积**（支持批量 `--watchlist`/`--positions`、`LBR_IV_HISTORY_DIR` 与日常问股静默补录） |
| `calc_iv_rank.py` | iv_history + 1年HV30代理 | `get_option_underlying_overview`(IV_RANK) | `(当前-最低)/(最高-最低)`；样本不足时默认提供 `hv_52w_proxy`（`--strict` 关闭） |
| `calc_iv_percentile.py` | iv_history + 1年HV30代理 | `get_option_underlying_overview`(IV_PERCENTILE) | 低于当前 IV 天数占比；样本不足时默认提供 `hv_52w_proxy`（`--strict` 关闭） |

### 🔴 C 档:不支持(Longbridge 无数据源)

| Futu 能力 | 为什么不支持 |
|---|---|
| `get_option_event`(期权异动大单/扫单) | 需要逐笔期权成交 + 服务端 SWEEP/BLOCK 标记,Longbridge 无 OPRA 逐笔推送 |
| `get_option_zero_dte_*`(0DTE 筛选) | 依赖异动数据流 |
| `get_option_earnings_screener`(财报 IV Crush) | 需历史 IV + 财报日关联,Longbridge 不提供 |
| `get_option_seller_screener`(卖方策略筛选) | 需全市场扫描 + 年化收益计算 |
| `get_option_event_alert` / 推送 | 异动告警系统 |
| `get_option_screen`(期权筛选器) | 需服务端多因子扫描 |
| `get_option_underlying_rank` / `get_option_rank` | 排行榜需服务端聚合 |
| `get_option_underlying_overview`(批量 IV 快照) | 需批量查询(可多次调 chain 近似,但非原生) |
| `get_option_strategy_analysis`(组合摆盘价 bid/ask) | Longbridge 不提供期权组合摆盘 |

---

## 已知限制（历史样本，不代表本次验证当前接口）

### 1. `option quote` 对单合约返回空
```
longbridge option quote AAPL260918C00200000 → []
```
**现象**:所有美股 OCC 代码查询都返回空数组,但 `option chain --date` 正常返回 IV。
**原因推测**:CLI 的 `option quote` 可能需要订阅该合约,或 OCC 格式要求不同(token 已确认含 OPRA 权限)。
**当前路径**:单合约通过 `calc-index` 获取可用原生 Greeks，缺失时才用 BS 公式(chain IV 作输入)回退。两种来源在输出中区分；BS 不含股息或提前行权。

### 2. `option chain` 只返回实时数据,无法查历史
```
longbridge option chain AAPL.US --date 2026-07-01 → []
```
**影响**:IV Rank / IV Percentile / IV 时间序列无法靠回溯历史 chain 得到。
**解决**:`get_iv_history.py` 采用**本地累积模式**（支持问股每日静默补录、`--watchlist`/`--positions` 批量采集及 `LBR_IV_HISTORY_DIR` 目录自定义），按市场日期采集恒定30日期限 IV(总方差插值，不外推)。旧的非恒定期限记录仍保留，但不计入 Rank/Percentile；本次采集失败时不把旧值作为当前。本地样本不足 20 天时，`calc_iv_rank.py` 与 `calc_iv_percentile.py` 默认使用过去 1 年滚动 `HV30` 提供冷启动代理分位（`hv_52w_proxy`，不冒充真实历史 IV，`--strict` 可强制报错）；采集时间并不证明上游报价实时。

### 3. 港股期权可能不支持
```
longbridge option volume daily 700.HK → {"stats": []}
```
文档 Quote Coverage 中港股未列期权(仅列 OPRA 美股期权)。本 skill 脚本对港股可能返回空。
→ **v0.4.0 补位**:港股衍生品经 `warrant` 命令覆盖(涡轮/权证,
`scripts/quote/get_warrant.py`,⚠️ 仅 HK)。

### 4. P/C 比率仅美股
`option volume daily` 仅支持美股 OPRA。

### 5. IV 数值形式
chain 的 IV 字段是小数（0.214 = 21.4%），calc-index 的样本为百分数字符串（如 `22.40%`）。公共封装按端点转换为小数，显示字段再转成百分比（`iv_pct`）。

### 6. 0.6.0 计算边界
显式非标准期权链记录排除；标准合约乘数为100。默认到期时间采用纽约16:00（规则半日市按 13:00 ET 收盘），同日收盘后自动跳过该到期日；交易所临时提前收市和特殊结算仍需合同/日历数据。BS 不可微折点明确拒绝 Greeks。完整说明见 [审计修复记录](../docs/audit-fixes-2026-11-03.md)。

### 7. 0.6.2 实盘修正
chain 同一行权价可能返回多行(零值行或陈旧垃圾行 + 真实行,行序每次不同),`get_option_chain()` 在入口按 call/put 两侧分别合并,每个行权价只返回一行。IV/HV 比率改为期限对齐,不再默认取最近到期日。说明与实证见 [0.6.2 修复记录](../docs/fixes-2026-11-24-high-priority.md)。

### 8. 0.6.3 / 0.6.5 实盘修正
常规时段之外 quote 的 `last` 是上一个常规时段的收盘价,盘前/盘后/夜盘的最新价在 `pre_market` / `post_market` / `overnight` 块里。`get_underlying_price()` 取最新时段的价格并记录来源(`get_underlying_price_info` / `price_source_note`,0.6.5 起 `_regular_session_state` 同步排除美股节假日与半日市提前收盘);需要与期权链 IV、日 K 处在同一时点的场合用 `regular_session_price`(0.6.5 起涵盖 `get_option_volatility`、`calc_expected_move`、`get_iv_term_structure` 的链上 ATM 选档，且自动跳过尚无 IV 的新挂牌周链)。以「现价」为基准的期权量(如距现价百分比、GEX@现价、行权概率)在盘前/盘后/夜盘按延长时段最新价计算。期权到期损益的零成交腿不再按零成本。说明与实证见 [0.6.3 修复记录](../docs/fixes-2026-11-25-medium-priority.md) 与 [0.6.5 修复记录](../docs/fixes-2026-11-25-us-live-spotcheck.md)。

---

## 数据字段对照

### `option chain --date` 返回字段(Longbridge)
```
strike, call_iv, put_iv, call_last, put_last, call_vol, put_vol, standard
```
⚠️ **不返回** OCC 代码(call_symbol/put_symbol),需用 `build_occ_code()` 构造。
⚠️ **同一行权价可能返回两行**(实测 2026-11-24:TSLA 2026-11-27 有 20 个行权价各两行,一行为全零或陈旧垃圾值,先后顺序每次调用都变),`get_option_chain()` 已统一合并;直接调用 `run_cli("option","chain",...)` 的调用方需自行处理。chain 只有 `last` 没有买卖价,翼部行权价的最新价可能陈旧。

### `option volume daily` 返回字段(Longbridge)
```
timestamp, total_call_volume, total_put_volume, total_volume,
total_call_open_interest, total_put_open_interest, total_open_interest,
put_call_volume_ratio, put_call_open_interest_ratio
```

### Futu 对应字段(参考)
Futu 的 `get_option_quote` 额外返回:delta/gamma/theta/vega/rho/implied_volatility/open_interest/volume。
Longbridge 的 `option quote` 单合约仍返回空,但 v0.3.2 起可经 **calc-index 按合约获取原生 Greeks + OI**(get_option_quote.py 已接入,BS 回退)。
