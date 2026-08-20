---
name: longbridge-pro
description: |
  长桥(Longbridge)数据增强 skill,只读无交易。九大模块:
  ①期权分析(链/Greeks/IV/HV/微笑/P-C比率/损益/策略/Wall/GEX/IV Crush/EM/风险逆转/期限结构/Max Pain,美股OPRA)
  ②异动追踪 ③主力资金流(大中小单/分钟流/港股经纪商持仓/沽空)
  ④事件日历(财报/除权除息) ⑤市场情绪(温度/热度榜/简报)
  ⑥技术面(MA/MACD/RSI/KDJ/BOLL/ATR/OBV/量比/52周/信号/评分/相对强度/Beta)
  ⑦基本面(估值分位/分析师评级/目标价/EPS预测/财务健康/股息)
  ⑧日内微观(VWAP/盘口压力/逐笔主动买卖) ⑨买卖决策仪表盘。
  Triggers: 期权,期权链,Greeks,IV,隐含波动率,波动率微笑,P/C比率,损益,期权策略,
  straddle,spread,butterfly,collar,异动,大单,资金流,主力,经纪商持仓,沽空,做空,
  财报日历,分红日历,除权除息,市场温度,热度榜,Put Wall,GEX,IV Crush,
  技术指标,技术分析,均线,MACD,RSI,KDJ,布林,ATR,OBV,量比,金叉,死叉,超买超卖,
  52周新高,支撑阻力,Beta,相对强度,估值分位,市盈率,分析师,评级,目标价,EPS预测,
  ROE,毛利率,负债率,自由现金流,财务健康,股息,股息率,收息,VWAP,盘口,买卖盘,
  主动买卖,逐笔,隐含波动幅度,风险逆转,Max Pain,期限结构,该买吗,该卖吗,买卖信号,
  多空对照,仪表盘,option chain,put call ratio,capital flow,short sale,
  earnings calendar,market temperature,expected move,risk reversal,order flow
license: MIT
metadata:
  author: community
  version: "0.3.1"
  risk_level: read_only
  requires_login: false
  default_install: true
  requires_mcp: false
  tier: read
---

# Longbridge Pro

长桥多维度数据增强 skill。在官方 longbridge 系列基础上加工原始接口,提供更深的分析能力。
覆盖九大模块:① 期权分析 ② 异动追踪 ③ 主力资金流 ④ 事件日历 ⑤ 市场情绪
⑥ 技术面 ⑦ 基本面 ⑧ 日内微观 ⑨ 买卖决策仪表盘。

> **语言规则**:根据用户输入语言自动回复。
> **安全提示**:本 skill 只读,无任何交易功能。

## 能力边界(重要)

- **期权部分**:实现 A 档(原生)+ B 档(计算),不实现 C 档(期权逐笔异动/0DTE —— Longbridge 无数据源)。
  详见 [references/capability-map.md](references/capability-map.md)。
- **新增模块**(异动/资金流/日历/情绪/技术/基本面/日内/决策):加工 Longbridge CLI 原生数据 + 跨模块融合分析。
  详见 [references/new-modules-map.md](references/new-modules-map.md)。

### 已知限制(实测)
1. **`option quote` 单合约查询返回空** → Greeks 改用 Black-Scholes 公式(chain IV 作输入)计算
2. **`option chain` 无法查历史** → IV Rank/Percentile 靠 `get_iv_history.py` 本地累积,需多日运行
3. **仅支持美股 OPRA** → 港股/A 股期权数据可能为空
4. **P/C 比率仅美股** → `option volume daily` 不支持港股
5. **chain 无按行权价的 OI** → Put/Call Wall 和 GEX 用成交量近似(脚本已标注)
6. **broker-holding 仅港股** → 美股调用会优雅报错
7. **short 数据 US/HK 字段不同** → 脚本按字段存在性自动识别市场
8. **盘口/逐笔为瞬时快照** → 休市时为最后快照,主动买卖比样本取决于时段
9. **估值历史美股常见只有 PE** → 部分标的才有 PB/PS,脚本按实际返回处理
10. **技术面打分权重/灯号阈值为设计选择** → 可按风格调整,输出已标注

## 前提条件

1. **longbridge CLI** 已安装并登录(`longbridge auth login`)
2. **Python 3.8+**(本 skill 用 Python 做 BS/HV 等计算,不需要 longport SDK)
3. 期权模块需账户开通 **OPRA 期权行情权限**(其余模块不需要;基本面/日内/技术面仅需股票行情)

环境检查:
```bash
python scripts/check_env.py
```

## 脚本路径查找

本 skill 脚本按模块分目录:
```bash
{SKILL_BASE_DIR}/scripts/
├── quote/       # ① 期权模块(原 derivatives-pro + EM/RR/期限结构/MaxPain)
├── market/      # ② 异动追踪
├── flow/        # ③ 资金流/主力
├── calendar/    # ④ 事件日历
├── sentiment/   # ⑤ 市场情绪
├── technical/   # ⑥ 技术面(指标库/综合评分/相对强度)
├── fundamental/ # ⑦ 基本面(估值/评级/财务/股息)
├── intraday/    # ⑧ 日内微观(VWAP/盘口/逐笔)
└── decision/    # ⑨ 买卖决策仪表盘
```
运行示例:
```bash
python scripts/market/get_anomaly.py --market US
python scripts/flow/get_capital_flow.py AAPL.US
python scripts/decision/analyze_buy_sell.py AAPL.US
```

## 命令速查

### 🟢 A 档:原生数据

#### 获取期权到期日
```bash
python scripts/quote/get_option_expiration.py AAPL.US [--limit 10] [--json]
```

#### 获取期权链(某到期日的所有行权价 + IV)
```bash
python scripts/quote/get_option_chain.py AAPL.US --date 2026-09-18 [--near-atm 313] [--json]
```
- 返回 strike / call_iv / put_iv / call_last / put_last / call_vol / put_vol
- `--near-atm 313` 只显示现价 ±20% 范围

#### 获取期权成交量与 P/C 比率
```bash
# 实时 Call/Put 成交量 + P/C 比率
python scripts/quote/get_option_volume.py AAPL.US [--json]
# 每日 P/C 比率时间序列(含持仓量)
python scripts/quote/get_option_volume.py AAPL.US --daily --count 60 [--json]
```
- ⚠️ 仅美股

#### 解析/构造 OCC 期权代码
```bash
python scripts/quote/resolve_option_code.py --underlying AAPL.US --expiry 2026-09-18 --strike 315 --type CALL [--json]
```
- Longbridge chain 不返回 OCC 代码,本脚本构造并验证

### 🟡 B 档:计算

#### 单合约报价 + Greeks(BS 计算)
```bash
python scripts/quote/get_option_quote.py AAPL.US 2026-08-14 315 CALL [--rate 0.045] [--json]
```
- IV 来自 chain,Greeks 用 Black-Scholes 计算
- theta=/日, vega=/1%IV, rho=/1%rate

#### IV vs HV 波动率分析
```bash
python scripts/quote/get_option_volatility.py AAPL.US [--expiry 2026-09-18] [--hv-days 30] [--json]
```
- IV 取自 chain,HV 用 K 线自算(年化)
- 给出 IV/HV 比率 + 贵贱判断

#### 波动率微笑/偏度
```bash
python scripts/quote/get_vol_smile.py AAPL.US --expiry 2026-09-18 [--json]
```
- 各 strike 的 IV 曲线 + Put 偏度(OTM put - ATM)

#### IV 历史(本地累积)
```bash
# 追加今天数据 + 显示历史(建议每日运行)
python scripts/quote/get_iv_history.py AAPL.US [--json]
# 只读不追加
python scripts/quote/get_iv_history.py AAPL.US --no-append
```
- ⚠️ Longbridge 不提供历史 IV,靠本地累积(`~/.lbr_iv_history/<symbol>.json`)
- 数据存到 `~/.lbr_iv_history/AAPL_US.json`

#### IV Rank
```bash
python scripts/quote/calc_iv_rank.py AAPL.US [--min-points 20] [--json]
```
- 依赖 iv_history 积累(建议 ≥ 20 个交易日)

#### IV Percentile
```bash
python scripts/quote/calc_iv_percentile.py AAPL.US [--min-points 20] [--json]
```

#### 行权概率
```bash
python scripts/quote/calc_exercise_prob.py AAPL.US 2026-08-14 315 CALL [--json]
```
- BS 闭式解 N(d2) + |delta| 近似,两种都给

#### 组合 Greeks 加权
```bash
python scripts/quote/calc_option_greeks.py '<JSON腿列表>' [--json]
# 或文件
python scripts/quote/calc_option_greeks.py legs.json
```
腿 JSON 格式:
```json
[
  {"underlying":"AAPL.US","expiry":"2026-08-14","strike":315,"type":"CALL","action":"BUY","quantity":1},
  {"underlying":"AAPL.US","expiry":"2026-08-14","strike":315,"type":"PUT","action":"BUY","quantity":1}
]
```

#### 到期损益分析
```bash
python scripts/quote/calc_option_pnl.py '<JSON腿列表>' [--json]
```
- 盈亏平衡点、最大盈亏、各腿成本

#### 生成标准策略腿(8 种)
```bash
python scripts/quote/get_option_strategy.py AAPL.US 2026-08-14 STRADDLE [--json]
```
支持策略:`STRADDLE` / `STRANGLE` / `BULL_CALL_SPREAD` / `BEAR_PUT_SPREAD` /
`BUTTERFLY` / `COLLAR` / `COVERED_CALL` / `CASH_SECURED_PUT`
- 输出的 legs JSON 可直接传给 `calc_option_greeks.py` 或 `calc_option_pnl.py`

#### Put/Call Wall(关键支撑/阻力)
```bash
python scripts/quote/get_put_call_wall.py AAPL.US --date 2026-09-18 [--walls 3] [--json]
```
- 找成交量最大的 Put 行权价(支撑)/ Call 行权价(阻力)
- ⚠️ 基于成交量近似(Longbridge chain 无按行权价的 OI)

#### Gamma Exposure (GEX)
```bash
python scripts/quote/calc_gex.py AAPL.US --date 2026-09-18 [--rate 0.045] [--json]
```
- 各 strike gamma × 成交量加权,算净 GEX 和翻转点
- 正 GEX=抑制波动,负 GEX=放大波动

#### 财报 IV Crush 分析
```bash
python scripts/quote/analyze_iv_crush.py AAPL.US [--json]
```
- 结合财报日历 + 本地 IV 历史,分析财报前后的 IV 变化
- 依赖 `get_iv_history.py` 累积数据

---

### 🔵 异动追踪(模块①)

#### 异动信号(大单/封板/放量)
```bash
python scripts/market/get_anomaly.py [--market US|HK|CN|SG] [--symbol 700.HK] [--count 50] [--json]
```
- 返回大单买卖/封涨跌停等信号,含情绪方向(利多/利空)

#### 涨跌异动榜(含新闻解读)
```bash
python scripts/market/get_top_movers.py [--market US] [--sort hot|time|change] [--count 20] [--json]
```
- 波动超 20 日均值的个股,自动关联新闻摘要

---

### 💰 主力资金流(模块③)

#### 资金流向(大中小单分布 + 分钟流)
```bash
python scripts/flow/get_capital_flow.py AAPL.US [--flow] [--json]
```
- 默认:大/中/小单流入流出 + 净额 + 主力方向(单位为当地货币完整元,CLI 原始"万"已换算)
- `--flow`:当日分钟级资金净流入时序

#### 港股经纪商持仓(⚠️仅港股)
```bash
python scripts/flow/get_broker_holding.py 700.HK [--period rct_1|5|20|60] [--detail] [--daily --broker B01274] [--json]
```
- top10 买卖经纪商 / 全量明细 / 单经纪商历史曲线
- 港股特色数据(富途无),反映机构在哪个经纪商加减仓

#### 沽空数据
```bash
python scripts/flow/get_short_sale.py AAPL.US [--position] [--count 20] [--json]
```
- 默认:日沽空成交量比率(趋势判断)
- `--position`:未平仓持仓(美股 days_to_cover / 港股 cost)

---

### 📅 事件日历(模块④)

#### 财报日历
```bash
python scripts/calendar/get_earnings_calendar.py [--market US] [--symbol AAPL.US] [--watchlist] [--count 30] [--json]
```
- 预测/实际 EPS,标"已公布"vs"待公布"

#### 除权除息日历
```bash
python scripts/calendar/get_dividend_calendar.py [--market US] [--symbol AAPL.US] [--count 50] [--json]
```
- 每股分红金额、类型(常规/特别)、派息日

---

### 🌡️ 市场情绪(模块⑤)

#### 市场温度指数
```bash
python scripts/sentiment/get_market_temp.py [US|HK|CN|SG] [--history --start DATE --end DATE] [--json]
```
- 0-100 温度(>70 偏热,<30 偏冷)+ 估值/情绪分项

#### 热度排行榜
```bash
python scripts/sentiment/get_heat_rank.py [--market US]                           # 列所有 tab
python scripts/sentiment/get_heat_rank.py --key hot_all-us [--count 20] [--json]  # 拉具体榜
```
- 综合热度/热度上升/热门交易/热议/关注度,各市场(US/HK/CN/SG)

---

### 📈 技术面(模块⑥)

#### 全套技术指标 + 信号
```bash
python scripts/technical/calc_indicators.py AAPL.US [--count 300] [--json]
```
- MA5/10/20/60/120/250、EMA、MACD、RSI、KDJ、BOLL、ATR、OBV、MFI、量比、ROC、Williams %R、CCI、52周位置、最大回撤(前复权 K 线计算)
- 信号:均线多空排列、MA5/20 与 MACD 金叉死叉、KDJ 超买卖、20日新高新低、年线上下

#### 技术面综合评分(0-100)
```bash
python scripts/technical/calc_technical_score.py AAPL.US [--json]
```
- 四维:趋势(30)/动量(25)/量能(20)/位置(25),≥70 强势 / 50-70 偏多 / 30-50 偏弱

#### 相对强度 + Beta(vs 大盘)
```bash
python scripts/technical/calc_relative_strength.py AAPL.US [--benchmark QQQ.US] [--json]
```
- 1周~1年各窗口跑赢/跑输基准 + Beta 弹性;默认基准 US=SPY / HK=2800 / A股=510300

---

### 🏦 基本面(模块⑦)

#### 估值分位(当前 vs 5年历史 + 同行)
```bash
python scripts/fundamental/get_valuation_percentile.py AAPL.US [--json]
```
- PE/PB 当前值处于历史百分位(<30% 便宜 / >70% 偏贵)+ 行业同行排名

#### 分析师共识 + 目标价 + EPS 预测
```bash
python scripts/fundamental/get_analyst_consensus.py AAPL.US [--json]
```
- 买入/跑赢/持有/跑输/卖出分布、目标价区间 vs 现价空间、EPS 预测分歧度

#### 财务健康(三大报表)
```bash
python scripts/fundamental/get_financial_health.py AAPL.US [--json]
```
- 营收/净利/毛利/ROE/负债率/现金流 + 红绿灯评级(实测字段中文名匹配)

#### 股息质量
```bash
python scripts/fundamental/get_dividend_quality.py AAPL.US [--json]
```
- TTM 股息率、连续分红年数、年度增长(仅完整年份)、频率稳定性

---

### ⚡ 日内微观(模块⑧)

#### VWAP 分析
```bash
python scripts/intraday/get_vwap_analysis.py AAPL.US [--date 20260819] [--json]
```
- 现价 vs 当日 VWAP 偏离、上方时间占比、当日区间位置 → 日内强弱

#### 盘口买卖压力
```bash
python scripts/intraday/get_orderbook_pressure.py AAPL.US [--json]
```
- L2 深度失衡率、买卖盘量比、最大挂单墙(隐形支撑/阻力)、加权中枢

#### 逐笔主动买卖比(Order Flow)
```bash
python scripts/intraday/get_trade_flow.py AAPL.US [--count 300] [--big 1000] [--json]
```
- 主动买/卖量占比(量的口径+金额口径)、大单统计、尾盘情绪

---

### 🧮 期权补充(模块①扩展)

#### 隐含波动幅度(Expected Move)
```bash
python scripts/quote/calc_expected_move.py AAPL.US [--date 2026-09-18] [--all] [--json]
```
- ATM straddle 法:市场定价的到期前 ±波动区间(1σ),财报前判断"赌多大行情"

#### IV 期限结构
```bash
python scripts/quote/get_iv_term_structure.py AAPL.US [--count 8] [--json]
```
- 各到期日 ATM IV 连线:Contango/Backwardation + 事件溢价到期日检测

#### 25-Delta 风险逆转
```bash
python scripts/quote/calc_risk_reversal.py AAPL.US [--date 2026-09-18] [--delta 0.25] [--json]
```
- IV(25Δ Call) - IV(25Δ Put):负值=下行保护占优(恐慌),正值=上行需求

#### Max Pain(最大痛点)
```bash
python scripts/quote/calc_max_pain.py AAPL.US [--date 2026-09-18] [--json]
```
- 期权到期"引力位"(⚠️成交量近似 OI),距到期越近参考意义越大

---

### 🎯 跨模块旗舰

#### 买卖决策仪表盘(六维聚合)
```bash
python scripts/decision/analyze_buy_sell.py AAPL.US [--json]
```
- 技术面30% + 估值面15% + 资金面20% + 期权定位10% + 分析师15% + 事件风险10%
- 输出:六维得分 + 多头/空头因素对照 + 综合信号(看多/偏多/中性/偏空/看空)

#### 单标的异动综合打分
```bash
python scripts/market/calc_anomaly_score.py AAPL.US [--market US] [--json]
```
- 融合异动信号 + 资金流 + 涨跌幅 + 异动榜,输出 0-100 综合分 + 方向

#### 每日市场简报
```bash
python scripts/sentiment/daily_briefing.py [--market US] [--no-pc] [--json]
```
- 一键聚合:温度 + 热度榜 top5 + 异动榜 top5 + 异动统计 + 大盘 P/C 比率


## 典型工作流

### 工作流 1:分析某标的期权情绪
```bash
# 1. 看 P/C 比率趋势
python scripts/quote/get_option_volume.py AAPL.US --daily --count 20
# 2. 看 IV 贵贱
python scripts/quote/get_option_volatility.py AAPL.US
# 3. 看波动率微笑(判断市场对下行担忧)
python scripts/quote/get_vol_smile.py AAPL.US
```

### 工作流 2:评估一个期权策略
```bash
# 1. 生成策略腿
python scripts/quote/get_option_strategy.py AAPL.US 2026-08-14 BULL_CALL_SPREAD
# 2. 分析组合 Greeks
python scripts/quote/calc_option_greeks.py '<复制的 legs JSON>'
# 3. 分析到期损益
python scripts/quote/calc_option_pnl.py '<复制的 legs JSON>'
```

### 工作流 3:长期跟踪 IV(配 cron 每日运行)
```bash
# 每天 1 次,积累 IV 历史
0 22 * * 1-5 python scripts/quote/get_iv_history.py AAPL.US
# 攒够 20 天后计算 IV Rank
python scripts/quote/calc_iv_rank.py AAPL.US
```

### 工作流 4:每日开盘前看市场全景
```bash
# 一键生成简报(温度 + 热度榜 + 异动 + P/C)
python scripts/sentiment/daily_briefing.py --market US
```

### 工作流 5:深度分析某只异动股
```bash
# 1. 看异动综合打分(融合多数据源)
python scripts/market/calc_anomaly_score.py TSLA.US
# 2. 看主力资金流向
python scripts/flow/get_capital_flow.py TSLA.US --flow
# 3. 港股还要看经纪商持仓(南向/外资态度)
python scripts/flow/get_broker_holding.py 700.HK --detail
# 4. 看是否在沽空压力下
python scripts/flow/get_short_sale.py TSLA.US --position
```

### 工作流 6:期权关键价位 + 做市商压力
```bash
# 1. 找 Put/Call Wall(支撑阻力)
python scripts/quote/get_put_call_wall.py AAPL.US --date 2026-09-18
# 2. 看 GEX(做市商对冲压力)
python scripts/quote/calc_gex.py AAPL.US --date 2026-09-18
# 3. 财报前看 IV Crush 风险
python scripts/quote/analyze_iv_crush.py AAPL.US
```

### 工作流 7:判断"该不该买"(一站式)
```bash
# 1. 六维仪表盘(技术+估值+资金+期权+分析师+事件)
python scripts/decision/analyze_buy_sell.py AAPL.US
# 2. 深挖:估值贵不贵
python scripts/fundamental/get_valuation_percentile.py AAPL.US
# 3. 深挖:技术面信号明细
python scripts/technical/calc_indicators.py AAPL.US
# 4. 深挖:是否跑赢大盘
python scripts/technical/calc_relative_strength.py AAPL.US
```

### 工作流 8:财报前后的期权决策
```bash
# 1. 市场押注多大行情(Expected Move)
python scripts/quote/calc_expected_move.py AAPL.US --all
# 2. 近月是否含事件溢价(期限结构)
python scripts/quote/get_iv_term_structure.py AAPL.US
# 3. 下行担忧程度(风险逆转)
python scripts/quote/calc_risk_reversal.py AAPL.US --date 2026-09-18
```

## 与官方 skill 的关系

- **官方 `longbridge` 系列**(derivatives/fundamentals/market-data 等):prompt-only,基础查询
- **本 skill `longbridge-pro`**:加工增强,在原生数据上做 Greeks/HV/IV Rank/异动打分/资金流分析/简报等深度计算
- 两者可并存,原生查询仍可用官方 skill,深度分析用本 skill

## 文件布局

```
longbridge-pro/
├── SKILL.md
├── references/
│   ├── capability-map.md      # 期权部分:Futu↔Longbridge 能力映射(含 C 档缺失)
│   ├── new-modules-map.md     # 各模块:CLI 字段映射 + 已知限制
│   └── calc-formulas.md       # 数学公式参考
└── scripts/
    ├── common.py              # 公共模块(CLI 封装/BS/HV/异动/资金流/估值/盘口等)
    ├── check_env.py           # 环境预检
    ├── quote/                 # ① 期权模块(17 脚本 + 4 个补充)
    │   ├── ...                #   (见上方命令速查)
    │   ├── calc_expected_move.py      # 补充:隐含波动幅度(ATM straddle)
    │   ├── get_iv_term_structure.py   # 补充:IV 期限结构 + 事件溢价
    │   ├── calc_risk_reversal.py      # 补充:25Δ 风险逆转
    │   └── calc_max_pain.py           # 补充:Max Pain(成交量近似)
    ├── market/                # ② 异动追踪(get_anomaly/get_top_movers/calc_anomaly_score)
    ├── flow/                  # ③ 主力资金流(capital_flow/broker_holding/short_sale)
    ├── calendar/              # ④ 事件日历(earnings/dividend)
    ├── sentiment/             # ⑤ 市场情绪(market_temp/heat_rank/daily_briefing)
    ├── technical/             # ⑥ 技术面
    │   ├── indicators.py               # 指标数学库(纯函数,可复用)
    │   ├── calc_indicators.py          # 全套指标 + 信号检测
    │   ├── calc_technical_score.py     # 技术面综合评分(0-100)
    │   └── calc_relative_strength.py   # 相对强度 + Beta(vs 大盘)
    ├── fundamental/           # ⑦ 基本面
    │   ├── get_valuation_percentile.py # 估值历史分位 + 同行对比
    │   ├── get_analyst_consensus.py    # 分析师共识/目标价/EPS预测
    │   ├── get_financial_health.py     # 财务健康(三大报表+红绿灯)
    │   └── get_dividend_quality.py     # 股息质量(TTM/连续性/增长)
    ├── intraday/              # ⑧ 日内微观
    │   ├── get_vwap_analysis.py        # VWAP 偏离 + 日内强弱
    │   ├── get_orderbook_pressure.py   # L2 盘口失衡 + 挂单墙
    │   └── get_trade_flow.py           # 逐笔主动买卖比 + 大单
    └── decision/              # ⑨ 买卖决策
        └── analyze_buy_sell.py         # 六维聚合仪表盘(旗舰)
```

## 错误处理

| 错误 | 原因 | 解决 |
|---|---|---|
| `找不到 longbridge CLI` | 未安装 | 从 longbridge.com 下载安装 |
| `Token 失效` | token 过期 | `longbridge auth login` |
| `无可用到期日` | 非美股或无期权 | 确认标的支持 OPRA 期权 |
| `历史 IV 数据不足` | iv_history 未积累 | 多次运行 get_iv_history.py |
| `chain 中无有效 IV` | 该行权价无成交 | 换流动性更好的到期日/行权价 |
| `无经纪商数据` | broker-holding 传了非港股 | 仅港股支持,确认 symbol 是 .HK |
| `无资金流数据` | 标的当日无交易 | 确认是交易日且标的有流动性 |
| `K 线数据不足` | 新股/退市/停牌 | 换 --count 更小或确认标的状态 |
| `无估值/评级数据` | 覆盖不足(小票/新股) | 该维度仪表盘会标 N/A 并降权 |
| `无逐笔/盘口数据` | 休市时段 | 盘中运行,或接受最后快照 |
