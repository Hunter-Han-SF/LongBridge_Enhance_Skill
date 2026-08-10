# LongBridge Enhance Skill

[English](README.md) | **[中文](README.zh-CN.md)**

> 基于 [Longbridge OpenAPI](https://open.longbridge.com) 的社区期权分析增强工具。
> 提供 Black-Scholes 希腊值、历史波动率、IV Rank/Percentile、波动率微笑、认沽认购比率、策略损益分析等本地计算能力。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 这是什么

官方的 `longbridge-derivatives` skill 通过 Longbridge CLI 提供**原始期权链数据**(行权价、IV、价格)。本增强 skill 在其之上叠加了**计算层** —— Black-Scholes 定价、希腊值、波动率分析、策略损益等 CLI 本身不提供的能力。

它的目标是复刻同类券商(如富途 OpenAPI 期权套件)的期权分析能力,并根据 Longbridge API 实际暴露的数据做了适配。

## 功能

### 🟢 原生数据(封装自 Longbridge CLI)
- **期权到期日** — 列出所有可交易到期日
- **期权链** — 各行权价的 IV / 最新价 / 成交量
- **认沽认购比率(P/C ratio)** — 实时快照 + 每日时间序列(含持仓量)
- **OCC 代码解析器** — 构造并验证 OCC 期权合约代码

### 🟡 计算分析(核心价值)
- **单合约希腊值** — Delta / Gamma / Theta / Vega / Rho(Black-Scholes 计算)
- **IV vs HV** — 隐含波动率(来自期权链)对比历史波动率(来自 K 线),判断期权贵贱
- **波动率微笑与偏度** — 各行权价 IV 曲线 + Put 偏度(下行担忧指标)
- **IV Rank 与 IV Percentile** — 基于本地累积(见下方限制说明)
- **行权概率** — BS 闭式解 N(d2) + |delta| 近似
- **组合希腊值** — 多腿加权 Greeks,正确处理 BUY/SELL 方向
- **到期损益分析** — 盈亏平衡点(线性插值)、最大盈亏
- **策略腿生成器** — 8 种标准策略(Straddle、Strangle、价差、蝶式、领口、备兑、CSP)

## 环境要求

- **Longbridge CLI** 已安装并登录(`longbridge auth login`)
- **Python 3.8+**(无需第三方包 —— 纯标准库实现)
- Longbridge 账户已开通 **OPRA 美股期权行情**权限

## 安装

### 方式 A:作为 ZCode / Claude Code skill

将本文件夹复制到你的 skills 目录:

```bash
# ZCode
cp -r longbridge-derivatives-pro ~/.zcode/skills/

# Claude Code
cp -r longbridge-derivatives-pro ~/.claude/skills/
```

验证环境:

```bash
python scripts/check_env.py
```

### 方式 B:OpenClaw(一条命令安装)

```bash
openclaw skills install git:Hunter-Han-SF/LongBridge_Enhance_Skill
```

### 方式 C:独立脚本

直接 clone 使用 —— 脚本在任何有 Python + Longbridge CLI 的地方都能跑:

```bash
git clone https://github.com/Hunter-Han-SF/LongBridge_Enhance_Skill.git
cd LongBridge_Enhance_Skill
python scripts/check_env.py
```

## 快速上手

```bash
# AAPL 期权链
python scripts/quote/get_option_chain.py AAPL.US --date 2026-09-18

# AAPL 的 IV 贵不贵?(IV vs HV)
python scripts/quote/get_option_volatility.py AAPL.US

# 某合约的希腊值(Black-Scholes 计算)
python scripts/quote/get_option_quote.py AAPL.US 2026-08-14 315 CALL

# 分析一个牛市看涨价差的损益
python scripts/quote/get_option_strategy.py AAPL.US 2026-08-14 BULL_CALL_SPREAD
# ...然后把生成的 legs JSON 传给:
python scripts/quote/calc_option_pnl.py '<legs-json>'
```

完整命令参考见 [`SKILL.md`](SKILL.md)。

## 已知限制

这些是 Longbridge API 的**数据源限制**,不是 bug:

1. **单合约 `option quote` 返回空** — CLI 的 `option quote <OCC>` 目前对所有合约返回 `[]`(尽管有 OPRA 权限,原因不明)。因此希腊值通过 Black-Scholes 公式用期权链中的 IV 计算,而非服务端原生返回。

2. **无历史 IV** — `option chain` 只返回实时数据,无法查询过去日期。IV Rank / IV Percentile 采用**本地累积**模式:每天运行一次 `get_iv_history.py`,在 `~/.lbr_iv_history/` 中逐步建立序列。

3. **仅支持美股期权(OPRA)** — 港股 / A 股期权数据返回空,这是 Longbridge 的覆盖范围决定的。

4. **认沽认购比率仅限美股** — `option volume daily` 不支持港股。

完整的 富途 ↔ Longbridge 能力映射(包括哪些**无法实现**的能力 —— 期权异动、0DTE 筛选等),见 [`references/capability-map.md`](references/capability-map.md)。

## 未包含的功能(及原因)

同类券商期权 API 的某些能力在 Longbridge 上**根本无法实现**:

- ❌ 期权异动追踪 / 扫单 / 大单检测(需要逐笔 OPRA 成交流 + 交易所标记)
- ❌ 0DTE 末日期权筛选(依赖上述数据)
- ❌ 财报 IV Crush 预测(需要服务端历史 IV + 财报日关联)
- ❌ 卖方策略筛选器(年化收益率排序,需要全市场扫描)

这些是服务端专有数据产品,不是通用 API 输出。

## 计算验证

所有计算均已通过理论约束交叉验证:
- Black-Scholes:Put-Call 平价成立(误差 < 3e-14),Gamma/Vega 的 Call=Put 对称性精确,Delta(Call) - Delta(Put) = 1
- 历史波动率:与 `statistics.stdev` 一致到浮点精度
- 损益盈亏平衡:线性插值,已与闭式公式对照验证

详见 [`references/calc-formulas.md`](references/calc-formulas.md)。

## 商标声明

**Longbridge** 是 Longbridge Securities 的商标。**富途(Futu)** 是富途控股的商标。本项目是独立的社区工具,与两者无隶属或背书关系,仅调用公开文档的 Longbridge OpenAPI。详见 [LICENSE](LICENSE)。

## 许可证

[MIT](LICENSE)
