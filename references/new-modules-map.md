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

## 模块①扩展 期权现货联动

### 关键突破:按行权价的真实 OI(calc-index)

chain 本身仍无按行权价的 OI,但实测 **`calc-index` 可按单个期权合约查询 OI 与原生 Greeks**:

```bash
longbridge calc-index MSFT260821C485000.US --fields oi,iv,delta,gamma,theta,vega,rho --format json
# → {symbol, oi:"3741", iv:"22.40%", delta:"0.479", gamma:"0.046", theta:"-0.054", vega:"0.154", rho:"0.014", strike, exp, last_done}
```

要点(实测 2026-08,CLI 0.26.0):
- **合约代码格式与 OCC 不同**:行权价×1000 后**不补零**(`C485000`,OCC 是 `C00485000`),
  尾缀 `.US`。`common.build_lbr_option_symbol()` 已封装
- **支持一次传多个合约**(实测 ≥6 个),不存在的合约静默跳过(返回行数变少)
- **iv 是百分比字符串**("22.40%"),`get_option_contract_metrics()` 已归一化为小数
- 限频 10 次/秒;`get_chain_oi()` 默认只查现价 ±25%、离 ATM 最近 60 档(约 12 次调用),
  并带进程级缓存

据此升级(成交量仅作 OI 不可用时的回退,输出标注 weight_mode):
- **get_option_oi.py**:按行权价 OI 表 + P/C OI 比率(存量口径)+ OI 墙
- **calc_max_pain.py**:真实 OI 加权
- **calc_gex.py**:OI 加权 + 原生 gamma(缺失时 BS 回退)
- **get_put_call_wall.py**:OI 墙(约定:Call Wall 只在 ≥现价、Put Wall 只在 ≤现价 中找)
- **get_option_quote.py**:原生 Greeks 优先(greeks_source="native"),BS 回退,附带 OI

Gamma Profile 方法论(calc_gamma_profile.py,2026-08-20):
- **跨到期日聚合**:窗口内(默认60天)所有到期日的 (strike, IV, OI, T) 腿求和;
  sticky-strike 近似(IV 固定当前值),gamma 随假设价位用 BS 重算
- **Flip 插值**:±range 网格算 GEX(S),符号变化处线性插值,取离现价最近者;
  无过零时自动扩域(×1.5、上限0.40);单链翻转点同样升级(calc_gex.py 的
  `_find_flip_profile`),旧启发式已弃用
- **细粒度 S/R**:call/put OI 高斯核密度(带宽=行权价间距)局部极大值 + 抛物线
  插值 → 非整数价位;注意与第三方的"隐含波动分位 S/R"定义不同(我们=OI 密度墙)
- 实测:1DTE 深度价内 Call 重仓的链(如 MSFT 08-21)可能全区间无过零 —— 这是
  数学正确的结果(1DTE gamma 极度局域化),旧启发式在此类链上会给假翻转点

交叉验证(与第三方期权分析站对照,2026-08-20):
- NVDA Gamma Flip:本 skill 203.36 vs 网站 206.28(60天口径,差 1.4%)✅
- MSFT Gamma Flip:本 skill 373.27 vs 网站 383.84(60天口径,差 2.7%,不同日快照)✅
- NVDA 第一阻力:本 skill 220.52(插值) vs 网站 219.80 ✅
- Gamma 翻转点:本 skill 387.5 vs 网站 383.84 ✅
- Call Wall 500(+3.2%)在网站阻力区 492.56/502.18 内 ✅
- P/C OI 比率 0.381 vs 网站 0.430(不同到期日快照,同量级)✅
- Max Pain 差异属口径不同:网站用的是已到期的 0DTE 链(OI 集中在 ATM),
  本 skill 查询存续链(深度价内 Call 大持仓会把痛点拉低,数学正确)

### chain 无按行权价的 OI(旧限制,已由 calc-index 解决)

`longbridge option chain <SYM> --date <DATE>` 返回字段:
```
strike, call_iv, put_iv, call_last, put_last, call_vol, put_vol, standard
```

⚠️ chain 本身只有成交量(call_vol/put_vol),`option volume daily` 只有全市场汇总 OI。
**此限制已由 calc-index 按合约查询解决**(见上节);Wall/GEX/MaxPain 现为真实 OI 口径,
成交量仅作 calc-index 不可用时的回退(脚本输出标注 weight_mode)。

### GEX 计算约定(v0.3.2 起真实 OI 口径)

每 strike 的 GEX:
```
call_gex = gamma_call × call_oi × 100 × S² × 0.01    (正)
put_gex  = -gamma_put × put_oi × 100 × S² × 0.01     (负,对冲方向相反)
net_gex(K) = call_gex + put_gex
```
(gamma 优先取 calc-index 原生值,缺失时 BS;OI 不可用时回退 call_vol/put_vol 并标注)
跨到期日聚合剖面与插值 Flip 见 calc_gamma_profile.py(公式见 calc-formulas.md §11)。
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
| Put/Call Wall / GEX / Max Pain | ~~成交量代理~~ → 已升级真实 OI(calc-index),成交量仅回退 | 符号约定为行业惯例(SpotGamma 约定),非绝对真理 |
| 异动综合打分 | 权重(异动40/资金30/涨跌20/榜10)与阈值为设计选择 | 可按需调整 |
| IV Crush 检测 | 依赖本地 IV 累积,用"单日跌>20%"近似财报效应 | 需每日运行 get_iv_history 积累 |

---

# v0.4.0 新增模块字段映射(实测 2026-08-21,CLI 0.26.0;quant 修复复核于 0.27.1)

对应 common.py 的 v0.4.0 封装段与 25 个新脚本。单测见 `tests/`(夹具即本节真实输出)。

## 模块⑩ 选股器(screener)

```bash
longbridge screener strategies                 # [{id, name, type('platform')}]
longbridge screener run <ID>                   # {items: [...]}
longbridge screener filter KEY:MIN:MAX ... --market HK
longbridge screener indicators                 # [{id, key, name, unit, min, max}]
```

- `run`/`filter` 的 items: `{symbol, name, industry, marketcap, pettm, pbmrq,
  prevchg, prevclose, salesgrowthyoy}`(空值是**空字符串**,不是 null)
- 常用 key(实测 25+):marketcap/circulating_marketcap/assets/liabilities/la/leverage/
  bpsmrq/bpsgrowthyoy/sales/netincome/epsttm/roe/netmargin/roa/asset_turnover/
  netincomegrowthyoy/salesgrowthyoy/epsgrowthyoy/assetgrowthyoy/divyld/dpseps/
  fiveyearavgdps;维度 key:market/industry/tag
- `prevchg` 直接是百分数(16.25=+16.25%),与 industry-rank 的分数形式不同

## 模块①补充:港股涡轮(warrant,仅HK)

| 命令 | 返回 | 坑 |
|---|---|---|
| `warrant 700.HK` | `[{symbol, name, type, expiry, last, leverage_ratio}]` | **list 的 type 不可信**(实测 61304 标 Call,quote 却返回 Bear;700.HK 712 条几乎全 Call) |
| `warrant quote <SYM...>` | `[{symbol, type, expiry, last, prev_close, implied_vol}]` | **type 词汇混用**:'Call'/'Bull'=认购,'Bear'/'Put'=认沽(同一命令两种都见过);implied_vol 常见 0.000(无数据) |
| `warrant issuers` | `[{id, name_cn, name_en}]` | — |

`get_warrant.py` 的方向判断以 quote 为准(`--enrich` 批量补全,每批 10 只)。

## 模块③补充:经纪商队列(brokers / participants,仅HK)

- `brokers 700.HK` → `{asks/bids: [{position, broker_ids: [int]}]}`
  ⚠️ **无价格字段**(position=1 即卖一/买一,价格需用 depth 对齐)
- `participants` → `[{broker_id, name_cn, name_en}]`
  ⚠️ broker_id 是**字符串**,且有多值条目 `'7707, 7708, 7709'`(需拆分登记);
  `get_participants()` 已拆分为逐 id 行

## 模块④补充:日历新类别 + IPO

finance-calendar 六类别同构(`{date, list:[{date, count, infos[]}]}`):
- `split`: infos[].content 为"5 股合并为 1 股"中文(脚本正则解析比例)
- `ipo`: 与 `ipo` 命令的 calendar 子命令数据同源
- `macrodata`: data_kv 的 type= previous/estimate/actual
- `closed`: ext.holiday_date/holiday_type(full_day/half_day)

`ipo` 命令(阶段列表/详情):
- `ipo subscriptions|wait-listing|listed` → `{hk: [...], us: [...]}` 双市场合并返回;
  `us-*` 变体只含 us 键
- 条目: `{symbol, name, description, ipo_date(Unix秒), issue_price, currency,
  mart_begin/mart_end(暗盘RFC3339), result_date, sub_state, tags, win_qty}`
- `ipo detail <SYM>` → `{profile: {hk: {industry, investors:[基石], issue_price,
  prospectus, profile}}, holdings: {ipo_max_purchase, finance_fee_rate},
  eligibility: {can_subscribe}}`
  ⚠️ profile 里的日期字段是 Unix 秒原始值(mart_begin 等),展示时需自行转换

## 模块⑤补充:宏观指标(macrodata)

- 列表: `macrodata [--keyword] [--country]` → `{count, has_more, limit,
  list: [{indicator_code, name, country, importance('1'-'3'), periodicity, describe}]}`
- 历史: `macrodata <CODE>` → `{count, data: [{period, actual_value,
  forecast_value, previous_value, release_at(Unix秒), unit}]}`
- ⚠️ **文档示例 code 'US00175' 已失效**(报 not found),真实 code 是纯数字如 '30771936',
  必须从列表模式拿
- `finance-calendar macrodata`(按日期)与 `macrodata <CODE>`(按指标)是同一数据的两个维度

## 模块⑥补充:quant run(pine 可用,navi 服务端故障)

- 语法(PineScript):`indicator("标题","副题",precision=N)` / `strategy("名")`;
  `x1=input(20,"fast")`;`ta.ema(close,n)`/`ta.rsi(close,n)`/`[a,b,c]=ta.macd(close,12,26,9)`;
  `plot(序列,"名")`;回测用 `ta.crossover/crossunder` + `strategy.entry/close`
- **实测(2026-08-21,CLI 0.27.1)**:
  - navi 路径:internal server error(官方文档 Navi 原版示例同样失败)→ 不要用
  - pine 路径:正常
  - **JSON 模式缺口**:events_json 只含 K 线(barStart/barEnd)+sessionInfo,
    **不含 plot 序列值**;chart_json 为空串,indicator 的 report_json 为 "null"
  - 指标值取法:pretty 输出有 Series 表(名称/Bars/First/Last/Min/Max+sparkline),
    `run_quant_indicator.py` 以 `fmt=raw` 抓取并解析(ANSI 剥离 + 按 │ 分列)
  - 回测取法:JSON 模式的 report_json 是嵌套 JSON 字符串,
    含 config(initialCapital/commission)+ performanceAll(netProfit/maxDrawdown/
    sharpeRatio/profitFactor/winRate/numberOfWining/LosingTrades/buyHoldReturn...)
- `--input '[14]'` 覆盖 input.*() 默认值;`--language pine` 必须显式传(默认 navi 会 500)
- 交叉验证实测:服务端 EMA20/RSI14 与本地 indicators.py 末值相对偏差 <0.02% ✅

## 模块⑦补充:基本面新命令

| 命令 | 返回结构 | 要点 |
|---|---|---|
| `compare A B --currency` | `{list: [{counter_id, pe, pb, ps, roe, roa, net_margin, div_yld, market_value, history:[{date,pe,pb,ps}], ...}]}` | ≤5 只;单只自动对比同行;脚本做组内排名(估值低好/质量高好) |
| `business-segments` | `{bus_ids, business: [{id, name, percent, value, yoy}]}` | value 是当地货币原始值;脚本算 CR1/CR2 |
| `industry-rank --market` | `{items: [{name, lists: [{counter_id(BK/US/INxxx), chg, leading_ticker, leading_chg, ...}]}]}` | ⚠️ **chg 是分数**(0.1544=+15.44%,与 pretty 输出对照确认);BK id 在 lists[].counter_id |
| `industry-peers <BK_ID>` | `{chain: {name, level, stock_num, next:[子行业]}, top: {name}}` | BK id 来自 industry-rank |
| `industry-valuation dist <SYM>` | `{pe/pb/ps: {value, median, high, low, rank_index, rank_total, ranking(0-1)}}` | ranking>0.7=行业内偏贵;部分标的只有 pe;getter 按实际 metric 处理 |
| `consensus` | `{currency, list: [{period_text('Q2 2027'), fiscal_year, fiscal_period, details: [{key, name, estimate, actual, is_released}]}]}` | 报告期标签在 period_text;脚本算超/逊预期 |
| `corp-action` | `{items: [{action('DividendExDate'), act_type, act_desc, date('20260813'), date_type, date_zone}]}` | date 是 YYYYMMDD 无分隔符 |
| `operating`(仅HK) | `{list: [{financial: {currency, indicators: [{indicator_name, indicator_value('4589 亿'), yoy}]}}]}` | 指标值是带单位的中文串 |
| `company` | 扁平 dict(company_name/founded/employees/address/manager/...) | 大多数字段按标的覆盖度可能为空 |
| `executive` | `{professional_list: [{professionals: [{name, title, biography}]}]}` | biography 是长文 |

## 模块⑦信号源(内部人/机构)

| 命令 | 返回结构 | 要点 |
|---|---|---|
| `insider-trades`(仅US) | `[{owner, title, date, filing_date, type('EXERCISE'/'SELL'...), code('A'/'D'/'M'), shares, price, value, shares_after}]` | 数值字段已是原生数值(非字符串);脚本按 type+code 双重分类方向 |
| `investors` | `[{cik, name, aum_usd, rank, period}]` | ⚠️ **cik 必须保留字符串**(前导零有意义);`get_investor_rankings()` 已特殊处理(绕过数值化) |
| `investors <CIK>` | `{cik, firm, filing_date, holdings: [{cusip, name, shares, value_usd, weight_pct}]}` | cusip 含字母不会数值化 |
| `investors changes <CIK>` | `{added, changes: [{action(NEW/ADDED/REDUCED/EXITED), shares, prev_shares, delta_usd, delta_pct}]}` | delta_pct 新建时是字符串 'NEW' |
| `fund-holder` | `{lists: [{counter_id, code, name, position_ratio, report_date}]}` | position_ratio=占基金净值% |
| `shareholder` | `{shareholder_list: [{shareholder_name, percent_of_shares, shares_changed, report_date, stocks:[{code, chg}]}]}` | shares_changed 正=增持;⚠️ 个别条目 shareholder_name 为空 |

## 模块②/⑧补充:成分股 / 量价分布 / AH溢价

- `constituent HSI.HK --sort inflow` → `{rise_num, fall_num, flat_num, stocks: [...]}`
  - ⚠️ **chg 是分数**(0.0731=+7.31%,由 28.18→30.24 验证)
  - ⚠️ HSI 的 rise/fall/flat 实测全 0(不回填),美股指数需前缀点(.SPX.US)
  - 美股 ETF 默认 SEC N-PORT 全持仓(--limit 0 全量)
- `trade-stats 700.HK` → `{statistics: {avgprice, preclose, buy, sell, neutral,
  total_amount, trades_count, trade_date[]}, trades: [{price, buy_amount,
  sell_amount, neutral_amount}]}`(近5日)
  - Volume Profile 口径:vol(K) = buy+sell+neutral;POC=最大量价位;
    Value Area 从 POC 向更厚一侧贪心扩展至 70%
- `ah-premium 939.HK [--kline-type]` / `ah-premium intraday` → `{klines: [{ahpremium_rate,
  aprice, hprice, currency_rate, timestamp}]}`
  - **ahpremium_rate<0 = H股折价**(如 -0.266 = H 比 A 便宜 26.6%)
  - 仅 A+H 双市场标的;非双市场返回空 klines

## v0.4.0 新增已知坑汇总

13. **screener 的空值是空字符串**("",不是 null),to_float 处理无碍但判断存在性时注意
14. **industry-rank / constituent 的 chg 是分数**(×100 才是百分数;与 trade-stats 的
    prevchg(直接百分数)和 compare 的 pe(直接倍数)口径均不同)
15. **macrodata 文档示例 code 失效**:必须从列表模式拿真实 indicator_code
16. **quant run 的 navi 路径服务端 500**(2026-08-21 实测,官方示例同挂)→ pine 可用,脚本已切换
17. **CIK 前导零**:investors 的 cik 是 '0001422848' 形态,数值化会丢零;
    `get_investor_rankings()` 已保留原始字符串
18. **consensus 报告期标签在 period_text**(fiscal_year/fiscal_period 是拆开的字段)
