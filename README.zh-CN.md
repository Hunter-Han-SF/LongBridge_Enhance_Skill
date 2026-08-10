# LongBridge Enhance Skill (longbridge-pro)

[English](README.md) | **[中文](README.zh-CN.md)**

> 基于 [Longbridge OpenAPI](https://open.longbridge.com) 的社区多维度分析增强工具。
> 五大模块:① 期权分析(BS 希腊值、IV/HV、波动率微笑、P/C 比率、损益、Put/Call Wall、GEX、IV Crush)
> ② 异动追踪 ③ 主力资金流 ④ 事件日历 ⑤ 市场情绪 —— 全部基于 Longbridge CLI 数据本地计算。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 这是什么

官方的 `longbridge` skill 系列通过 Longbridge CLI 提供**原始数据**(期权链、行情、基本面)。本增强 skill 在其之上叠加了**计算与融合层** —— Black-Scholes 定价、希腊值、波动率分析、策略损益、异动打分、资金流分析、一键市场简报等 CLI 本身不提供的能力。

## 功能

### 🟢 模块①:期权分析(美股 OPRA)
- **期权链 / 到期日 / P-C 比率 / OCC 代码** — 原生数据封装
- **单合约希腊值** — Delta / Gamma / Theta / Vega / Rho(Black-Scholes 计算)
- **IV vs HV** — 隐含波动率(期权链)对比历史波动率(K 线自算)
- **波动率微笑与偏度** — 各行权价 IV 曲线 + Put 偏度
- **IV Rank 与 IV Percentile** — 基于本地累积
- **行权概率 / 组合希腊值 / 到期损益 / 8 种标准策略腿**
- **Put/Call Wall** — 成交量最大的行权价,判断支撑/阻力
- **Gamma Exposure (GEX)** — 做市商对冲压力 + 翻转点
- **财报 IV Crush** — 结合财报日历 + 本地 IV 历史分析

### 🔵 模块②:异动追踪
- **异动信号** — 大单买卖、封涨跌停,含利多/利空情绪标记
- **涨跌异动榜** — 波动超 20 日均值的个股 + 关联新闻
- **异动综合打分** — 单标的 0-100 综合分(融合信号 + 资金流 + 涨跌幅 + 异动榜)

### 💰 模块③:主力资金流
- **资金分布** — 大/中/小单流入流出 + 净额 + 分钟级资金流时序
- **港股经纪商持仓** — top10 买卖、全量明细、单经纪商历史(⚠️仅港股)
- **沽空数据** — 日沽空成交量比率 + 未平仓持仓(美股 days_to_cover / 港股 cost)

### 📅 模块④:事件日历
- **财报日历** — 预测/实际 EPS,标"已公布"vs"待公布"
- **除权除息日历** — 每股分红金额、类型(常规/特别)、派息日

### 🌡️ 模块⑤:市场情绪
- **市场温度** — 0-100 指数 + 估值/情绪分项 + 历史
- **热度排行榜** — 总热度/热度上升/热门交易/热议/关注度,各市场
- **每日简报** — 一键聚合(温度 + 热度榜 top5 + 异动榜 top5 + 异动统计 + SPY P/C 比率)

## 环境要求

- **Longbridge CLI** 已安装并登录(`longbridge auth login`)
- **Python 3.8+**(无需第三方包 —— 纯标准库实现)
- 期权模块需开通 **OPRA 美股期权行情**权限(模块②–⑤不需要)

## 安装

### 方式 A:作为 ZCode / Claude Code skill

复制或软链接本文件夹到你的 skills 目录:

```bash
# ZCode(推荐软链接,改代码立即生效)
mklink /D %USERPROFILE%\.zcode\skills\longbridge-pro F:\path\to\LongBridge_Enhance_Skill

# Claude Code
cp -r LongBridge_Enhance_Skill ~/.claude/skills/longbridge-pro
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
# === 期权 ===
python scripts/quote/get_option_volatility.py AAPL.US          # IV vs HV
python scripts/quote/get_put_call_wall.py AAPL.US --date 2026-09-18  # 支撑/阻力

# === 异动 & 资金流 ===
python scripts/market/get_top_movers.py --market US            # 异动榜+新闻
python scripts/flow/get_capital_flow.py AAPL.US --flow         # 分钟资金流
python scripts/flow/get_broker_holding.py 700.HK --detail      # 港股经纪商

# === 日历 & 情绪 ===
python scripts/calendar/get_earnings_calendar.py --market US
python scripts/sentiment/get_market_temp.py US

# === 一键每日简报 ===
python scripts/sentiment/daily_briefing.py --market US
```

完整命令参考见 [`SKILL.md`](SKILL.md)。

## 已知限制

这些是 Longbridge API 的**数据源限制**,不是 bug:

1. **单合约 `option quote` 返回空** — 希腊值改用 Black-Scholes 公式(chain IV 作输入)计算。
2. **无历史 IV** — IV Rank/Percentile 采用**本地累积**模式(每日运行 `get_iv_history.py`)。
3. **仅支持美股期权(OPRA)** — 港股/A 股期权数据返回空。
4. **期权链无按行权价的未平仓量(OI)** — Put/Call Wall 和 GEX 用成交量近似(输出已标注)。
5. **经纪商持仓仅港股** — 美股调用返回空。
6. **沽空数据 US/HK 字段不同** — 按字段存在性自动识别市场。

完整的 富途↔Longbridge 期权能力映射见 [`references/capability-map.md`](references/capability-map.md),
新模块 CLI 字段映射与限制见 [`references/new-modules-map.md`](references/new-modules-map.md)。

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
