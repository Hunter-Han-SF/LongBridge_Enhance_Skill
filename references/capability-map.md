# Futu ↔ Longbridge 期权能力映射表

本 skill 复刻 Futu 期权能力的 **A 档(原生)+ B 档(计算)**,**不实现 C 档**(Longbridge 无对应数据源)。

## 三档说明

| 档位 | 含义 | 实现方式 |
|---|---|---|
| 🟢 A 档 | Longbridge CLI 原生支持,直接包一层 | 调 `longbridge option/quote/kline` |
| 🟡 B 档 | Longbridge 不直接提供,但可用现有数据 + 数学计算得出 | CLI 拉数据 + Python 算 |
| 🔴 C 档 | Longbridge 根本没有数据源,无法实现 | 明确标注不支持 |

---

## 完整映射表

### 🟢 A 档:原生(5 个脚本)

| 本 skill 脚本 | CLI 命令 | 对应 Futu | 说明 |
|---|---|---|---|
| `get_option_expiration.py` | `option chain <UL>` | `get_option_expiration_date` | 到期日列表 |
| `get_option_chain.py` | `option chain <UL> --date` | `get_option_chain` | 某到期日的行权价 + IV + 价格 |
| `get_option_volume.py` | `option volume` / `volume daily` | `get_option_market_statistic` | 实时/每日 Call-Put 成交量 + **P/C 比率**(原生!) |
| `resolve_option_code.py` | `build_occ_code` + chain 验证 | `resolve_option_code` | 构造 OCC 代码(Longbridge chain 不返回 symbol) |
| `get_option_quote.py`(原生部分) | `option quote <OCC>` | `get_option_quote` | ⚠️ 当前返回空(见下方"已知限制") |

### 🟡 B 档:计算(10 个脚本)

| 本 skill 脚本 | 数据源 | 对应 Futu | 计算方法 |
|---|---|---|---|
| `get_option_volatility.py` | chain IV + kline | `get_option_volatility` | HV = std(ln收益)×√252;IV/HV 比率 |
| `get_vol_smile.py` | chain 各 strike IV | `get_option_volatility`(扩展) | 提取 smile + put skew |
| `get_option_quote.py`(BS 部分) | chain IV | `get_option_quote` | BS 公式算 delta/gamma/theta/vega/rho |
| `calc_option_greeks.py` | 各腿 chain IV | `get_option_strategy_analysis`(Greeks) | 多腿 Greeks 加权 |
| `calc_exercise_prob.py` | chain IV + 现价 | `get_option_exercise_probability` | BS N(d2) / |delta| 近似 |
| `calc_option_pnl.py` | chain last price | `get_option_strategy_analysis`(损益) | 到期损益曲线/盈亏平衡/最大盈亏 |
| `get_option_strategy.py` | chain + 现价 | `get_option_strategy` | 生成标准策略腿(8 种) |
| `get_iv_history.py` | 每日累积 chain IV | `get_option_underlying_his_volatility` | **本地累积**(见下方限制) |
| `calc_iv_rank.py` | iv_history 序列 | `get_option_underlying_overview`(IV_RANK) | (当前-最低)/(最高-最低) |
| `calc_iv_percentile.py` | iv_history 序列 | `get_option_underlying_overview`(IV_PERCENTILE) | 低于当前 IV 的天数占比 |

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

## 已知限制(实测得出)

### 1. `option quote` 对单合约返回空
```
longbridge option quote AAPL260918C00200000 → []
```
**现象**:所有美股 OCC 代码查询都返回空数组,但 `option chain --date` 正常返回 IV。
**原因推测**:CLI 的 `option quote` 可能需要订阅该合约,或 OCC 格式要求不同(token 已确认含 OPRA 权限)。
**影响**:单合约 Greeks 改用 BS 公式(chain IV 作输入)计算,与服务端可能有细微差异。
**升级路径**:若 `option quote` 后续可用,`get_option_quote.py` 会自动检测原生数据并优先使用。

### 2. `option chain` 只返回实时数据,无法查历史
```
longbridge option chain AAPL.US --date 2026-07-01 → []
```
**影响**:IV Rank / IV Percentile / IV 时间序列无法靠回溯历史 chain 得到。
**解决**:`get_iv_history.py` 采用**本地累积模式**,每次运行记录当天 IV,逐步建立序列。建议配 cron 每日运行。

### 3. 港股期权可能不支持
```
longbridge option volume daily 700.HK → {"stats": []}
```
文档 Quote Coverage 中港股未列期权(仅列 OPRA 美股期权)。本 skill 脚本对港股可能返回空。

### 4. P/C 比率仅美股
`option volume daily` 仅支持美股 OPRA。

### 5. IV 数值形式
Longbridge 的 IV 字段是**小数**(0.214 = 21.4%),与 Futu 的百分比形式不同。本 skill 统一用小数内部计算,输出时转百分比(`iv_pct`)。

---

## 数据字段对照

### `option chain --date` 返回字段(Longbridge)
```
strike, call_iv, put_iv, call_last, put_last, call_vol, put_vol, standard
```
⚠️ **不返回** OCC 代码(call_symbol/put_symbol),需用 `build_occ_code()` 构造。

### `option volume daily` 返回字段(Longbridge)
```
timestamp, total_call_volume, total_put_volume, total_volume,
total_call_open_interest, total_put_open_interest, total_open_interest,
put_call_volume_ratio, put_call_open_interest_ratio
```

### Futu 对应字段(参考)
Futu 的 `get_option_quote` 额外返回:delta/gamma/theta/vega/rho/implied_volatility/open_interest/volume。
Longbridge 的 `option quote` 单合约仍返回空,但 v0.3.2 起可经 **calc-index 按合约获取原生 Greeks + OI**(get_option_quote.py 已接入,BS 回退)。
