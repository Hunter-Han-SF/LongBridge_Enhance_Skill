# LongBridge Enhance Skill (longbridge-pro)

[English](README.md) | **[中文](README.zh-CN.md)**

> 基于 [Longbridge OpenAPI](https://open.longbridge.com) 的社区多维度分析增强工具。
> 十大模块:① 期权分析(原生 Greeks、IV/HV、波动率微笑、P/C 比率、损益、Put/Call Wall、GEX、IV Crush、
> Expected Move、风险逆转、IV 期限结构、Max Pain、OI 分布、Gamma Profile + 港股涡轮)
> ② 异动追踪(+指数成分/板块轮动/AH溢价) ③ 主力资金流(+经纪商队列) ④ 事件日历(财报/分红/拆股/IPO/宏观/休市/新股档案)
> ⑤ 市场情绪(+宏观指标历史) ⑥ 技术面(MA/MACD/RSI/KDJ/BOLL/ATR/OBV + 综合评分 + 相对强度/Beta + 服务端quant)
> ⑦ 基本面(估值分位/分析师共识/财务健康/股息质量/多股对比/业务分部/行业排行/财务共识/公司行动/经营回顾/公司档案
> + 内部人交易/13F机构持仓/基金持仓/机构股东)
> ⑧ 日内微观(VWAP/盘口失衡/逐笔主动买卖/量价分布Volume Profile) ⑨ 买卖决策仪表盘 ⑩ 选股器(预设策略/自定义条件)
> —— 全部基于 Longbridge CLI 数据本地计算,含 77 项单元测试。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 这是什么

官方的 `longbridge` skill 系列通过 Longbridge CLI 提供**原始数据**(期权链、行情、基本面)。本增强 skill 在其之上叠加了**计算与融合层** —— Black-Scholes 定价、希腊值、波动率分析、策略损益、异动打分、资金流分析、一键市场简报等 CLI 本身不提供的能力。

## 功能

### 🟢 模块①:期权分析(美股 OPRA)
- **期权链 / 到期日 / P-C 比率 / OCC 代码** — 原生数据封装
- **单合约报价** — 服务端原生 Greeks 优先(calc-index,含 OI),Black-Scholes 回退
- **IV vs HV** — 隐含波动率(期权链)对比历史波动率(K 线自算)
- **波动率微笑与偏度** — 各行权价 IV 曲线 + Put 偏度
- **IV Rank 与 IV Percentile** — 基于本地累积
- **行权概率 / 组合希腊值 / 到期损益 / 8 种标准策略腿**
- **Put/Call Wall** — 真实 OI 墙(calc-index,成交量回退),判断支撑/阻力
- **Gamma Exposure (GEX)** — 真实 OI 加权(原生 gamma 优先)+ 剖面插值翻转点
- **Gamma Profile(旗舰)** — 跨到期日(默认60天)聚合 GEX 剖面 + 插值 Gamma Flip + OI 核密度细粒度支撑/阻力
- **期权 OI 分布** — 按行权价真实 OI + P/C OI 比率(存量口径)+ OI 墙
- **财报 IV Crush** — 结合财报日历 + 本地 IV 历史分析
- **港股涡轮**(仅HK) — 正股涡轮全景(杠杆/到期分布)+ 单合约报价 + 发行商;方向以 quote 为准

### 🔵 模块②:异动追踪
- **异动信号** — 大单买卖、封涨跌停,含利多/利空情绪标记
- **涨跌异动榜** — 波动超 20 日均值的个股 + 关联新闻
- **异动综合打分** — 单标的 0-100 综合分(融合信号 + 资金流 + 涨跌幅 + 异动榜)
- **指数/ETF 成分股** — 按涨跌/资金流入/成交额排序,板块轮动监控
- **A/H 溢价** — 双市场标的溢价 K 线/分时 + z-score + 收窄/走阔趋势

### 💰 模块③:主力资金流
- **资金分布** — 大/中/小单流入流出 + 净额 + 分钟级资金流时序
- **港股经纪商持仓** — top10 买卖、全量明细、单经纪商历史(⚠️仅港股)
- **经纪商买卖队列** — 每档价位是哪家机构挂单(名称解析,潜在托单/压单,仅HK)
- **沽空数据** — 日沽空成交量比率 + 未平仓持仓(美股 days_to_cover / 港股 cost)

### 📅 模块④:事件日历
- **财报日历** — 预测/实际 EPS,标"已公布"vs"待公布"
- **除权除息日历** — 每股分红金额、类型(常规/特别)、派息日
- **拆股/合股日历** — 比例自动解析("5 股合并为 1 股" → 5→1 合股)
- **IPO 全景** — 上市日历 / 认购中/暗盘/已上市阶段列表 / 新股档案(基石投资者+申购额度)
- **宏观数据发布日历 + 休市日历**

### 🌡️ 模块⑤:市场情绪
- **市场温度** — 0-100 指数 + 估值/情绪分项 + 历史
- **热度排行榜** — 总热度/热度上升/热门交易/热议/关注度,各市场
- **每日简报** — 一键聚合(温度 + 热度榜 top5 + 异动榜 top5 + 异动统计 + SPY P/C 比率)
- **宏观指标** — CPI/PMI/利率等历史 + 超预期/逊预期统计

### 📈 模块⑥:技术面
- **全套指标** — MA/EMA/MACD/RSI/KDJ/BOLL/ATR/OBV/MFI/量比/ROC/Williams %R/CCI/52周位置/最大回撤(前复权计算)
- **信号检测** — 均线多空排列、MA/MACD/KDJ 金叉死叉、超买超卖、20日新高新低、年线
- **综合评分** — 趋势/动量/量能/位置四维 0-100 打分
- **相对强度 + Beta** — 1周~1年跑赢/跑输大盘,默认基准 SPY/2800/510300
- **服务端 quant 指标/回测** — pine 预设(EMA/RSI/MACD + EMA交叉回测)+ 本地指标交叉验证(偏差<0.02%)

### 🏦 模块⑦:基本面
- **估值分位** — PE/PB 当前值 vs 5 年历史百分位 + 行业同行对比
- **分析师共识** — 评级分布、目标价空间、EPS 预测分歧度
- **财务健康** — 三大报表关键指标红绿灯(增长/盈利/杠杆/现金流)
- **股息质量** — TTM 股息率、连续分红年数、完整年度增长率
- **多股对比** — ≤5 只横向估值/质量对比 + 组内排名(估值低好/质量高好)
- **业务分部** — 营收拆分 + 集中度(CR1/CR2)
- **行业排行 + 层级树 + 行业估值分布** — 板块涨跌幅 + 领涨股 + 子行业 + 当前估值行业内分位
- **财务共识明细** — 科目级预测 vs 实际(超/逊预期标注)
- **公司行动 / 港股经营回顾 / 公司档案+高管**

### 🧠 模块⑦信号源(机构与内部人)
- **内部人交易**(SEC Form 4,仅US) — 净买入额 + 买卖统计 + 多空信号
- **13F 机构持仓** — AUM 排名 / 单机构持仓 / 两期变动(新建/加仓/减仓/清仓)
- **基金持仓 / 机构股东** — 谁在重仓、增减持方向

### ⚡ 模块⑧:日内微观
- **VWAP 分析** — 现价 vs 当日均价偏离 + 上方时间占比
- **盘口压力** — L2 深度失衡、买卖量比、最大挂单墙
- **主动买卖比** — 逐笔方向统计 + 大单检测 + 尾盘情绪
- **量价分布 Volume Profile**(近5日) — POC(最强支撑/阻力)+ Value Area 70% 区间

### 🎯 模块⑨:买卖决策仪表盘
- **六维聚合** — 技术 30% + 估值 15% + 资金 20% + 期权 10% + 分析师 15% + 事件风险 10%
- 输出多空因素对照 + 综合信号(看多/偏多/中性/偏空/看空)

### 🔍 模块⑩:选股器
- **预设策略** — 低估值/高盈利高成长/今日大涨等 17 个官方策略一键执行
- **自定义条件** — `pettm:10:50 roe:5:` 式指标筛选(25+ 个指标 key)
- **选股→打分工作流** — 筛出的股票直接送六维仪表盘

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
python scripts/quote/get_warrant.py 700.HK --enrich 20         # 港股涡轮

# === 异动 & 资金流 ===
python scripts/market/get_top_movers.py --market US            # 异动榜+新闻
python scripts/market/get_constituent.py HSI.HK --sort inflow  # 指数成分(板块轮动)
python scripts/flow/get_capital_flow.py AAPL.US --flow         # 分钟资金流
python scripts/flow/get_broker_holding.py 700.HK --detail      # 港股经纪商
python scripts/flow/get_broker_queue.py 700.HK                 # 经纪商买卖队列

# === 选股 ===
python scripts/screener/run_screener.py --filter pettm:5:30 --filter roe:10: --market HK

# === 日历 & 情绪 ===
python scripts/calendar/get_earnings_calendar.py --market US
python scripts/sentiment/get_market_temp.py US
python scripts/sentiment/get_macro_data.py --keyword CPI --country US   # 宏观指标

# === 技术面 & 基本面 & 日内 ===
python scripts/technical/calc_indicators.py AAPL.US        # 全套技术指标+信号
python scripts/fundamental/get_valuation_percentile.py AAPL.US  # 估值分位
python scripts/fundamental/compare_stocks.py AAPL.US MSFT.US NVDA.US  # 多股对比
python scripts/fundamental/get_insider_trades.py TSLA.US  # 内部人交易
python scripts/intraday/get_vwap_analysis.py AAPL.US       # VWAP
python scripts/intraday/get_trade_stats.py 700.HK          # 量价分布(POC/VA)

# === 一键每日简报 / 买卖仪表盘 ===
python scripts/sentiment/daily_briefing.py --market US
python scripts/decision/analyze_buy_sell.py AAPL.US        # 六维多空对照
```

跑单元测试(77 项,mock CLI 无网络依赖):

```bash
python -m unittest discover -s tests -v
```

完整命令参考见 [`SKILL.md`](SKILL.md)。

## 已知限制

这些是 Longbridge API 的**数据源限制**,不是 bug:

1. **单合约 `option quote` 返回空** — 希腊值改用 Black-Scholes 公式(chain IV 作输入)计算。
2. **无历史 IV** — IV Rank/Percentile 采用**本地累积**模式(每日运行 `get_iv_history.py`)。
3. **仅支持美股期权(OPRA)** — 港股/A 股期权数据返回空(港股衍生品用 `warrant` 涡轮)。
4. **~~期权链无按行权价的 OI~~(已解决)** — calc-index 可按合约查真实 OI + 原生 Greeks,Wall/GEX/MaxPain-P/C OI 已升级真 OI 口径(成交量仅作回退)。
5. **经纪商持仓/队列仅港股** — 美股调用返回空。
6. **沽空数据 US/HK 字段不同** — 按字段存在性自动识别市场。
7. **warrant list 的 type 字段不可信** — 真实方向以 quote 的 type 为准(Call/Bull=认购,Bear/Put=认沽)。
8. **~~`quant run` 服务端故障~~(已解决,pine 方案)** — Navi 路径服务端 500(实测 2026-08-21,官方示例同挂),PineScript 正常,内置预设已全部改用 pine;指标序列值经 pretty 表解析(JSON 模式不含 plot 值),回测走 report_json。
9. **macrodata 文档示例 code 已失效** — 必须从列表模式(`--keyword`)拿真实 indicator_code。

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
