---
name: longbridge-pro
description: |
  长桥多维度数据增强 skill。在官方 longbridge 系列基础上加工原始接口,
  提供更深的分析能力,覆盖五大模块:
  ① 期权分析(期权链/Greeks/IV/HV/波动率微笑/P-C比率/损益/策略,美股 OPRA)
  ② 异动追踪(大单异动/涨跌异动榜+关联新闻)
  ③ 主力资金流(大中小单分布/分钟流/港股经纪商持仓/沽空数据)
  ④ 事件日历(财报/除权除息/分拆/IPO/宏观)
  ⑤ 市场情绪(温度指数/热度排行榜)
  只读,无任何交易功能。
  Triggers: "期权", "期权链", "Greeks", "delta", "gamma", "theta", "vega", "rho",
  "IV", "隐含波动率", "HV", "历史波动率", "IV Rank", "IV Percentile", "波动率微笑",
  "P/C 比率", "put call ratio", "行权概率", "损益分析", "盈亏平衡", "期权策略",
  "straddle", "strangle", "spread", "butterfly", "collar", "covered call",
  "cash secured put", "0DTE", "期权报价", "option", "option chain", "option quote",
  "异动", "大单", "anomaly", "top movers", "异动榜",
  "资金流", "主力", "capital flow", "大单流入", "经纪商持仓", "broker holding",
  "沽空", "做空", "short sale", "short position", "沽空压力",
  "财报日历", "除权除息", "分红日历", "earnings calendar", "dividend calendar",
  "市场温度", "情绪", "market temperature", "热度榜", "popularity rank",
  "市场简报", "daily briefing", "Put Wall", "Call Wall", "GEX", "IV Crush",
  "期權", "異動", "資金流", "經紀商持倉", "沽空", "市場溫度"
license: MIT
metadata:
  author: community
  version: "0.2.0"
  risk_level: read_only
  requires_login: false
  default_install: true
  requires_mcp: false
  tier: read
---

# Longbridge Pro

长桥多维度数据增强 skill。在官方 longbridge 系列基础上加工原始接口,提供更深的分析能力。
覆盖五大模块:① 期权分析 ② 异动追踪 ③ 主力资金流 ④ 事件日历 ⑤ 市场情绪。

> **语言规则**:根据用户输入语言自动回复。
> **安全提示**:本 skill 只读,无任何交易功能。

## 能力边界(重要)

- **期权部分**:实现 A 档(原生)+ B 档(计算),不实现 C 档(期权逐笔异动/0DTE —— Longbridge 无数据源)。
  详见 [references/capability-map.md](references/capability-map.md)。
- **新增四模块**(异动/资金流/日历/情绪):加工 Longbridge CLI 原生数据 + 跨模块融合分析。
  详见 [references/new-modules-map.md](references/new-modules-map.md)。

### 已知限制(实测)
1. **`option quote` 单合约查询返回空** → Greeks 改用 Black-Scholes 公式(chain IV 作输入)计算
2. **`option chain` 无法查历史** → IV Rank/Percentile 靠 `get_iv_history.py` 本地累积,需多日运行
3. **仅支持美股 OPRA** → 港股/A 股期权数据可能为空
4. **P/C 比率仅美股** → `option volume daily` 不支持港股
5. **chain 无按行权价的 OI** → Put/Call Wall 和 GEX 用成交量近似(脚本已标注)
6. **broker-holding 仅港股** → 美股调用会优雅报错
7. **short 数据 US/HK 字段不同** → 脚本按字段存在性自动识别市场

## 前提条件

1. **longbridge CLI** 已安装并登录(`longbridge auth login`)
2. **Python 3.8+**(本 skill 用 Python 做 BS/HV 等计算,不需要 longport SDK)
3. 期权模块需账户开通 **OPRA 期权行情权限**(异动/资金流/日历/情绪模块不需要)

环境检查:
```bash
python scripts/check_env.py
```

## 脚本路径查找

本 skill 脚本按模块分目录:
```bash
{SKILL_BASE_DIR}/scripts/
├── quote/       # 期权模块(原 derivatives-pro)
├── market/      # 异动追踪
├── flow/        # 资金流/主力
├── calendar/    # 事件日历
└── sentiment/   # 市场情绪
```
运行示例:
```bash
python scripts/market/get_anomaly.py --market US
python scripts/flow/get_capital_flow.py AAPL.US
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
- 默认:大/中/小单流入流出 + 净额 + 主力方向
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

### 🎯 跨模块旗舰

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
│   ├── new-modules-map.md     # 新模块:CLI 字段映射 + 已知限制
│   └── calc-formulas.md       # B 档数学公式参考
└── scripts/
    ├── common.py              # 公共模块(CLI 封装/BS/HV/异动/资金流/日历/情绪)
    ├── check_env.py           # 环境预检
    ├── quote/                 # ① 期权模块(原 derivatives-pro)
    │   ├── get_option_expiration.py    # A 到期日
    │   ├── get_option_chain.py         # A 期权链
    │   ├── get_option_volume.py        # A 成交量+P/C比率
    │   ├── resolve_option_code.py      # A OCC代码
    │   ├── get_option_quote.py         # B 单合约报价+Greeks
    │   ├── get_option_volatility.py    # B IV vs HV
    │   ├── get_vol_smile.py            # B 波动率微笑
    │   ├── get_iv_history.py           # B IV历史(本地累积)
    │   ├── calc_iv_rank.py             # B IV Rank
    │   ├── calc_iv_percentile.py       # B IV Percentile
    │   ├── calc_exercise_prob.py       # B 行权概率
    │   ├── calc_option_greeks.py       # B 组合Greeks
    │   ├── calc_option_pnl.py          # B 损益分析
    │   ├── get_option_strategy.py      # B 策略腿生成
    │   ├── get_put_call_wall.py        # B Put/Call Wall(成交量近似)
    │   ├── calc_gex.py                 # B Gamma Exposure
    │   └── analyze_iv_crush.py         # B 财报 IV Crush
    ├── market/                # ② 异动追踪
    │   ├── get_anomaly.py              # 异动信号
    │   ├── get_top_movers.py           # 涨跌异动榜+新闻
    │   └── calc_anomaly_score.py       # 异动综合打分(跨模块)
    ├── flow/                  # ③ 主力资金流
    │   ├── get_capital_flow.py         # 大中小单分布+分钟流
    │   ├── get_broker_holding.py       # 港股经纪商持仓
    │   └── get_short_sale.py           # 沽空数据
    ├── calendar/              # ④ 事件日历
    │   ├── get_earnings_calendar.py    # 财报日历
    │   └── get_dividend_calendar.py    # 除权除息日历
    └── sentiment/             # ⑤ 市场情绪
        ├── get_market_temp.py          # 市场温度
        ├── get_heat_rank.py            # 热度排行榜
        └── daily_briefing.py           # 每日简报(跨模块)
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
