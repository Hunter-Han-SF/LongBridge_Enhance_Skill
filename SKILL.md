---
name: longbridge-derivatives-pro
description: |
  Longbridge 期权数据增强 skill(A+B 档),复刻 Futu 期权能力。
  覆盖:期权链/到期日、单合约 Greeks(Delta/Gamma/Theta/Vega/Rho,BS 计算)、
  IV/HV 波动率分析、IV Rank/Percentile、波动率微笑、P/C 比率(实时+时间序列)、
  行权概率、组合 Greeks、到期损益分析、标准策略腿生成(8 种)。
  限美股 OPRA。只读,无交易。
  Triggers: "期权", "期权链", "Greeks", "delta", "gamma", "theta", "vega", "rho",
  "IV", "隐含波动率", "HV", "历史波动率", "IV Rank", "IV Percentile", "波动率微笑",
  "P/C 比率", "put call ratio", "行权概率", "损益分析", "盈亏平衡", "期权策略",
  "straddle", "strangle", "spread", "butterfly", "collar", "covered call",
  "cash secured put", "0DTE", "期权报价", "期权链", "option", "option chain",
  "option quote", "期權", "隱含波動率", "歷史波動率", "波動率微笑", "損益分析"
license: MIT
metadata:
  author: community
  version: "0.1.0"
  risk_level: read_only
  requires_login: false
  default_install: true
  requires_mcp: false
  tier: read
---

# Longbridge Derivatives Pro

Longbridge 期权数据增强 skill,复刻 Futu 期权能力的 **A 档(原生)+ B 档(计算)**。

> **语言规则**:根据用户输入语言自动回复。
> **安全提示**:本 skill 只读,无任何交易功能。

## 能力边界(重要)

本 skill 实现 **A 档 + B 档**,**不实现 C 档**(期权异动/0DTE/扫单 —— Longbridge 无数据源)。
完整映射表见 [references/capability-map.md](references/capability-map.md)。

### 已知限制(实测)
1. **`option quote` 单合约查询返回空** → Greeks 改用 Black-Scholes 公式(chain IV 作输入)计算
2. **`option chain` 无法查历史** → IV Rank/Percentile 靠 `get_iv_history.py` 本地累积,需多日运行
3. **仅支持美股 OPRA** → 港股/A 股期权数据可能为空
4. **P/C 比率仅美股** → `option volume daily` 不支持港股

## 前提条件

1. **longbridge CLI** 已安装并登录(`longbridge auth login`)
2. **Python 3.8+**(本 skill 用 Python 做 BS/HV 等计算,不需要 longport SDK)
3. 账户已开通 **OPRA 期权行情权限**

环境检查:
```bash
python scripts/check_env.py
```

## 脚本路径查找

运行脚本前,先确认路径:
```bash
# 默认路径
ls skills/longbridge-derivatives-pro/scripts/quote/<script>.py
# 或 skill base directory
{SKILL_BASE_DIR}/scripts/quote/<script>.py
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

## 与官方 skill 的关系

- **官方 `longbridge-derivatives`**:prompt-only,基础期权链/窝轮查询
- **本 skill `longbridge-derivatives-pro`**:计算增强,BS Greeks / HV / IV Rank / 损益分析等
- 两者可并存,原生查询仍可用官方 skill,深度分析用本 skill

## 文件布局

```
longbridge-derivatives-pro/
├── SKILL.md
├── references/
│   ├── capability-map.md      # Futu↔Longbridge 能力映射(含 C 档缺失说明)
│   └── calc-formulas.md       # B 档数学公式参考
└── scripts/
    ├── common.py              # 公共模块(CLI 封装/BS/HV/OCC 构造)
    ├── check_env.py           # 环境预检
    └── quote/
        ├── get_option_expiration.py    # A 到期日
        ├── get_option_chain.py         # A 期权链
        ├── get_option_volume.py        # A 成交量+P/C比率
        ├── resolve_option_code.py      # A OCC代码
        ├── get_option_quote.py         # B 单合约报价+Greeks
        ├── get_option_volatility.py    # B IV vs HV
        ├── get_vol_smile.py            # B 波动率微笑
        ├── get_iv_history.py           # B IV历史(本地累积)
        ├── calc_iv_rank.py             # B IV Rank
        ├── calc_iv_percentile.py       # B IV Percentile
        ├── calc_exercise_prob.py       # B 行权概率
        ├── calc_option_greeks.py       # B 组合Greeks
        ├── calc_option_pnl.py          # B 损益分析
        └── get_option_strategy.py      # B 策略腿生成
```

## 错误处理

| 错误 | 原因 | 解决 |
|---|---|---|
| `找不到 longbridge CLI` | 未安装 | 从 longbridge.com 下载安装 |
| `Token 失效` | token 过期 | `longbridge auth login` |
| `无可用到期日` | 非美股或无期权 | 确认标的支持 OPRA 期权 |
| `历史 IV 数据不足` | iv_history 未积累 | 多次运行 get_iv_history.py |
| `chain 中无有效 IV` | 该行权价无成交 | 换流动性更好的到期日/行权价 |
