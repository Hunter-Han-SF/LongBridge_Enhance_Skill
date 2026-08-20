# 新增模块 CLI 字段映射 & 已知限制

本文档记录各增强模块(异动/资金流/日历/情绪/技术面/基本面/日内微观/决策)对 Longbridge CLI 的
封装细节、字段映射和实测限制。对标 [capability-map.md](capability-map.md)(期权部分)。

---

## 模块⑥ 技术面(本地计算,无新增 CLI 命令)

数据源:`kline --period day --adjust forward`(前复权,避免除权跳空污染均线)。
全部指标本地实现(`scripts/technical/indicators.py`,纯函数):
SMA/EMA/MACD(12,26,9)/RSI(Wilder)/KDJ(9,3,3)/BOLL(20,2,总体标准差)/ATR(Wilder)/
OBV(20期回归斜率)/MFI/量比/ROC/Williams %R/CCI/唐奇安/52周位置/最大回撤/Beta。

实现约定:
- EMA 种子 = 前 n 个的 SMA;KDJ 种子 K=D=50;BOLL 用总体方差(ddof=0)
- Beta 基于与基准按日期对齐后的日收益(US 默认 SPY / HK 2800 / A股 510300)
- 单元测试:单边涨跌边界值、Wilder RSI 对称序列=50、BOLL 与 statistics.pstdev 一致、
  Beta(2×市场)=2 等约束全部通过

---

## 模块⑦ 基本面

### `valuation` — 估值分析(5年历史 + 同行)

返回 `{overview, history, layouts, peers, stocks}`:
- `overview.metrics.{pe,...}.circle`:当前值;`desc`:AI 摘要(HTML)
- `history.metrics.{pe}.list`:约 5 年季度序列 `[{timestamp, value}]`,另有 `median/high/low`
- `peers.pe.list`:同行 `[{counter_id, name, value}]`(按估值降序)+ `industry_median`

⚠️ 美股常见只有 `pe` 一个 metric;部分标的才有 pb/ps。分位脚本按实际返回的 metric 处理。

### `institution-rating` — 机构评级

- `analyst.evaluate`: `{buy, over, hold, under, sell, no_opinion, total}`
  (over/under = 跑赢/跑输;buy+over 视为看多,sell+under 视为看空)
- `analyst.target`: `{highest_price, lowest_price, prev_close}`(无中值,需自算)
- `analyst.industry_name/industry_rank/industry_total`:行业归属与排名

### `forecast-eps` — EPS 预测

`items[]: {forecast_eps_mean/highest/lowest/median, forecast_start_date/end_date(Unix秒),
institution_up/down/total}`。分歧度 = (highest-lowest)/mean。

### `financial-report` — 三大报表

`list.{IS,BS,CF}.indicators[].accounts[]`,每个 account:
`{name(中文名), ranking_code(不总存在), ratio, values[]}`;
`values[]` **最新期在前**:`{period:"Q3 2026", year, fp_end, value, yoy}`。

⚠️ 科目按中文名匹配(如"营业收入"/"总负债");排名用 `industry_ranking`(如 "1/49")。
实测可用科目:每股收益/ROE/营业收入/净利润/毛利率/净利率/总资产/总负债/权益乘数/
每股净资产/净债务/经营现金流/自由现金流/资本支出。

### `dividend` — 分红历史

`list[]: {desc:"每股派息 0.27 USD", ex_date:"2026.08.10"(点分格式), record_date, payment_date}`。
金额与币种从 desc 正则解析。年度增长只用完整年份(当年期数少于上年时跳过)。

---

## 模块⑧ 日内微观

### `intraday` — 分钟线(自带 VWAP)

`[{time, price, avg_price(=VWAP), volume, turnover}]`,升序。`--date YYYYMMDD` 查历史,
`--session intraday|all` 过滤盘前盘后。

### `depth` — L2 盘口

`{asks:[{position, price, volume, order_num}], bids:[...]}`(卖档价格升序,买档降序)。
⚠️ 休市时通常只剩 1 档(最后快照),失衡指标此时参考意义有限。

### `trades` — 逐笔成交

`[{direction: "Up"|"Down", price, time, volume}]`,**最新在前**(`--count ≤1000`)。
Up=主动买(买方推动),Down=主动卖。大单阈值按股数(不同价位标的需调整)。

---

## 关键认知:CLI 是扁平命令

Longbridge 文档用 REST 路径(如 `/docs/cli/market-data/anomaly.md`),但 **CLI 实际是扁平命令**
(直接 `longbridge anomaly`,不是 `longbridge market-data anomaly`)。本文档统一用真实 CLI 命令名。

所有命令通用选项:`--format json` / `--schema`(查返回字段) / `--lang zh-CN|en` / `-v`(verbose)。

---

## 模块① 异动追踪

### `anomaly` — 异动信号

```bash
longbridge anomaly --market <HK|US|CN|SG> [--symbol <SYM>] [--count N]
```

返回结构:
```
{all_off: bool, changes: [...]}
```

| 字段 | 含义 | 实测值示例 |
|---|---|---|
| `alert_name` | 异动类型(中文) | 大笔买入/大笔卖出/封涨停/竞价异动 |
| `alert_type` | 类型编号 | 5=大笔买入, 6=大笔卖出, 11=波动异动, 13=竞价, 27/28=封涨跌停 |
| `emotion` | 情绪方向 | **1=利多, 2=利空** |
| `counter_id` | 标的内部 ID | `ST/US/DASH`(用 `counter_id_to_symbol()` 转) |
| `name` | 标的中文名 | Doordash |
| `change_values` | 异动描述 | `["800 股"]` |
| `alert_time` | Unix 时间戳(秒) | 1786132199 |
| `all_off` | 全市场无信号标记 | true 时 changes 为空 |

### `top-movers` — 涨跌异动榜(含新闻)

```bash
longbridge top-movers [--market <M>] [--sort hot|time|change] [--count N]
```

返回结构:
```
{events: [...], next_params, updated_at}
```

| 字段 | 含义 | 说明 |
|---|---|---|
| `events[].alert_reason` | 异动原因 | "波动超 20 日均值" |
| `events[].stock` | **标的信息(注意:不在顶层 counter_id)** | {symbol, name, last_done, change, ...} |
| `events[].post` | 关联新闻对象 | `desc_locale.original` 是中文摘要 |

⚠️ **关键坑**:`top-movers` 的标的信息在 `event.stock` 里(含 `symbol/name/last_done/change`),
**不是** `event.counter_id`(此字段不存在)。`post.counter_ids` 是相关标的列表。

---

## 模块③ 主力资金流

### `capital` — 资金分布 / 分钟流

```bash
longbridge capital <SYMBOL>           # 快照
longbridge capital <SYMBOL> --flow    # 分钟级时序
```

**快照**返回:
```
{capital_in: {large, medium, small}, capital_out: {large, medium, small}, symbol, timestamp}
```
⚠️ **单位实测结论:原始值单位是"万"**(AAPL 实测:原始合计 324,217,当日成交额 $159.5 亿;
按"元"解释仅占 0.002%,不合常理;按"万"解释 ≈ $32.4 亿,占成交额 20%,合理)。
`get_capital_flow_snapshot()` / `get_capital_flow_series()` 已统一 ×1e4 换算为当地货币完整单位
(美股=USD,港股=HKD),调用方无需再处理。

**分钟流**返回 `[{inflow, time}, ...]`。⚠️ 实测 `inflow` 是**当日累计净流入**(391 个点的
末值与快照 `net.total` 完全一致),不是每分钟增量。`get_capital_flow_series()` 已 ×1e4 换算
为当地货币完整单位,并计算 `minute_delta`(相邻分钟增量)供峰值分析使用。

### `broker-holding` — 港股经纪商持仓 ⚠️仅HK

```bash
longbridge broker-holding <SYM> [--period rct_1|5|20|60]   # top10 买卖
longbridge broker-holding detail <SYM>                      # 全量明细
longbridge broker-holding daily <SYM> --broker <ID>         # 单经纪商历史
```

**top 模式**:`{buy: [{name, parti_number, chg, strong}], sell: [...], updated_at}`
- `chg`: 该周期持仓变动股数(正=增持,负=减持)
- `parti_number`: 经纪商稳定 ID(如 `B01274`=摩根士丹利,`A00004`=港股通深)

**detail 模式**:`{list: [{name, parti_number, strong, ratio: {value, chg_1, chg_5, chg_20, chg_60}}]}`
- `ratio.value`: 占流通股比例(%),各 chg_N 是近 N 日变动

### `short-trades` / `short-positions` — 沽空数据

⚠️ **US / HK 字段不同**,本 skill 按 `nus_amount`(US)vs `balance`(HK)存在性自动识别市场。

| 命令 | 美股字段(FINRA) | 港股字段(HKEX) |
|---|---|---|
| `short-trades` | nus_amount, ny_amount, total_amount, rate, close | amount, balance, total_amount, rate, close |
| `short-positions` | **current_shares_short**, days_to_cover, rate, close | amount, balance, cost, rate, close |

⚠️ **字段名陷阱**:`short-positions` 美股文档说 `short_interest`,**实际返回字段是 `current_shares_short`**。
- US `days_to_cover` ≥5 提示逼空风险
- HK `cost` 是平均沽空成本价

---

## 模块④ 事件日历

### `finance-calendar` — 子命令式

```bash
longbridge finance-calendar <report|dividend|split|ipo|macrodata|closed> \
  [--market M] [--symbol SYM] [--filter watchlist|positions] \
  [--start DATE] [--end DATE] [--count N]
```

返回结构(所有子命令一致):
```
{date, list: [{date, count, infos: [...]}], next_date, result}
```

`infos[]` 关键字段:
| 字段 | 含义 |
|---|---|
| `counter_id` / `counter_name` | 标的 |
| `date` / `date_type` | 事件时间 + "盘前"/"盘后" + 时区 |
| `content` | 人类可读摘要 |
| `data_kv[]` | **结构化数据**:`{type, value, value_raw}`,value_raw 空=待公布 |
| `ext` | 分类扩展(report 有 industry,dividend 有 dividend_amount/payment_date 等) |

**report 的 data_kv.type**:`estimate_eps` / `actual_eps` / `estimate_revenue` / `actual_revenue`
**dividend 的 ext**:`dividend_amount` / `dividend_type`(regular/special) / `payment_date` / `record_date`

⚠️ **日历锚定日期**:默认返回的 `date` 是 API 的参考锚点(可能是历史日期),
需用 `--start/--end` 拉目标范围。

---

## 模块⑤ 市场情绪

### `market-temp` — 温度指数

```bash
longbridge market-temp <HK|US|CN|SG>              # 快照
longbridge market-temp <M> --history [--start --end]  # 时序
```

⚠️ **返回是键值对数组**,不是普通对象:
```
[{field: "Temperature", value: "72"}, {field: "Valuation", value: "82"}, ...]
```
本 skill 的 `get_market_temp()` 把它展平成 `{temperature, valuation, sentiment, description}`。

### `rank` — 热度榜(两步式)

```bash
longbridge rank [--market M]                    # 第一步:列 tab(key 列表)
longbridge rank --key <KEY> [--count N]         # 第二步:拉具体榜
```

**tab 列表**:`[{key, market, name}]`,如 `{key: "hot_all-us", name: "总热度"}`
- 可用 tab:hot_all / hot_up / trade_heat / discuss_heat / watchlist_heat × {us,hk,cn,sg}

**具体榜**:`{bmp, updated_at, lists: [...]}`
- `lists[]` 是**完整 quote+heat 对象**,字段极多(symbol/name/last_done/chg/inflow/balance/volume_rate/five_day_chg 等)
- ⚠️ 无独立 heat `score` 字段,排名由数组顺序隐含

---

## 模块⑤扩展 期权现货联动

### 关键限制:chain 无按行权价的 OI

`longbridge option chain <SYM> --date <DATE>` 返回字段:
```
strike, call_iv, put_iv, call_last, put_last, call_vol, put_vol, standard
```

⚠️ **只有成交量(call_vol/put_vol),没有未平仓量(OI)按行权价分布**。
`option volume daily` 只有全市场汇总 OI(total_call/put_open_interest)。

因此:
- **Put/Call Wall**: 用成交量代理(非真实 OI Wall)
- **GEX**: 用成交量加权(非真实 OI 加权)
- 这是对真实指标的近似,流动性好的标的近似度较高。脚本输出已明确标注。

### GEX 计算约定

每 strike 的 GEX:
```
call_gex = gamma_call × call_vol × 100 × S² × 0.01   (正)
put_gex  = -gamma_put × put_vol × 100 × S² × 0.01     (负,对冲方向相反)
net_gex(K) = call_gex + put_gex
```
- 正总 GEX → 做市商抑制波动(偏稳)
- 负总 GEX → 做市商放大波动(易剧烈行情)
- Gamma 翻转点:net_gex 跨越零的价位

---

## 通用注意事项

1. **所有数值字段都是字符串**:CLI 返回的数字都是 quote-wrapped,`normalize_records()` / `to_float()` 处理
2. **timestamp 是 Unix 秒(UTC 字符串)**:用 `datetime.fromtimestamp(n, tz=timezone.utc)` 转
3. **broker-holding 仅港股**:美股调用会返回空,脚本会优雅报错
4. **short 数据 US/HK 字段不同**:按 `nus_amount` 存在与否自动识别
5. **finance-calendar 锚定日期行为**:
   - 不传参数 → 返回 API 内部锚点(通常是最近一个有事件的日期)
   - 传 `--symbol` 单标的过滤 → 默认返回该标的**最近一次已发布**财报(历史),不返回未来待发布
   - 传 `--start/--end` → 按范围过滤,但单标的+start 组合可能返回空(实测)
   - 建议:查个股最近财报时不传 start;查全市场某段时间事件时传 start/end
6. **market-temp 是键值对数组**:返回 `[{field, value}, ...]`,不是普通对象,`get_market_temp()` 已展平
7. **rank 两步式**:先列 key 再拉榜,不能直接拉
8. **quote 的涨跌幅字段名**:实测是 `change_percentage`(百分比形式,"0.29"=0.29%),**不是** `change_pct`/`chg`/`change1m`
9. **auth 误判规避**:`_looks_like_auth_error()` 用带上下文的短语匹配,避免数据值里的 "401"(如 `turnover:"30617440165"`)、合法字段 `"status":"Normal"` 等被误判为 token 失效;且**仅在 CLI 报错(非零退出码)或输出整体不是 JSON 时才检测**,成功返回的数据内容(如新闻标题含 "access denied")不会触发
10. **"invalid" 包含子串 "valid"**:所有基于子串的 valid/invalid 判断(auth status、Token Status)必须**先判失效信号**再判 valid,否则失效 token 会被误判为有效
11. **期权到期日列表含过期日期**:chain 返回的到期日列表头部会带最近已到期的合约,`get_option_expirations()` 已过滤今天之前的日期(默认取 `expirations[0]` 的脚本依赖此行为)
12. **时间戳按 UTC 解析**:anomaly/short-trades/option volume daily 的 Unix 时间戳均按 UTC 转换,输出已标注(UTC 后缀或 `date_utc`/`alert_time UTC`),与市场当地时间可能不同

## 计算正确性验证

以下计算已通过理论约束或标准库交叉验证:

| 计算 | 验证方法 | 误差 |
|---|---|---|
| Black-Scholes 定价 | Put-Call Parity: C - P = S - K·e^(-rT) | < 3e-10 |
| BS Greeks | Gamma/Vega 的 Call=Put 对称性;Delta(Call) - Delta(Put) = 1 | 精确(浮点极限) |
| 历史波动率 HV | 与 `statistics.stdev(ln returns)` 对比 | < 1e-17 |
| IV Rank/Percentile | 纯统计定义,公式无歧义 | — |

以下为**近似值**(数据源限制,非计算错误,脚本输出已标注):

| 计算 | 近似原因 | 备注 |
|---|---|---|
| Put/Call Wall | chain 无按行权价的 OI,用**当日成交量**代理 | 流动性好的标的近似度高 |
| GEX | 同上,用成交量加权;符号为 SpotGamma 约定(假设做市商卖 call 买 put) | 符号方向是行业惯例,非绝对真理 |
| 异动综合打分 | 权重(异动40/资金30/涨跌20/榜10)与阈值为设计选择 | 可按需调整 |
| IV Crush 检测 | 依赖本地 IV 累积,用"单日跌>20%"近似财报效应 | 需每日运行 get_iv_history 积累 |
