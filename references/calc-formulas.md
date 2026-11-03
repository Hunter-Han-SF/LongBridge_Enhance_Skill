# B 档计算公式参考

本 skill 的 B 档能力用到的数学公式。通用公式见 `scripts/common.py`，各模块实现见下文。

## 1. 历史波动率 HV

```
HV = std(ln(close_i / close_{i-1})) × √252
```
- 收盘价取自 `kline --period day`
- 年化因子 252(美股交易日)
- 实现见 `common.calc_hv()`

## 2. IV vs HV 贵贱判断

```
比率 = IV / HV
> 1.3  → IV 偏贵(期权定价高于近期波动,考虑卖权)
< 0.8  → IV 偏便宜(考虑买权)
其他   → 合理区间
```
- IV 取自 chain 的 ATM call_iv / put_iv
- 实现见 `get_option_volatility.py`

## 3. IV Rank

```
IV Rank = (当前IV - N日最低IV) / (N日最高IV - N日最低IV) × 100
```
- 范围 0-100
- 对极端值敏感(单日异常 IV 会显著影响)
- 使用全部本地恒定 30 日期限样本，非固定一年滚动窗口；必须当次成功采集。旧的非恒定期限样本保留但不混算。
- 以包围 30 日的到期日插值总方差 `IV² × T`，再除以目标期限后开方；缺少一侧数据不外推。
- 所有样本 IV 相等时 Rank 约定显示 50，不代表已证明处于市场中位。
- 实现见 `calc_iv_rank.py`

## 4. IV Percentile

```
IV Percentile = (此前可比观测中 IV < 当前IV 的天数 / 此前可比观测天数) × 100
```
- 对异常值不敏感(用占比而非极差)
- 使用与 Rank 相同的可比序列，但分位的分子和分母都排除本次观测：历史分母为 `data_points - 1`；相同 IV 不计入小于当前的天数。中位数使用包含本次观测的完整序列。
- 实现见 `calc_iv_percentile.py`

## 5. 波动率微笑与偏度

```
Put Skew = OTM_put_IV - ATM_IV
> 0    → 市场担忧下行(downside fear)
≈ 0    → 中性
```
- OTM put 取 moneyness ≈ 0.85 的行权价
- 实现见 `get_vol_smile.py`

## 6. Black-Scholes Greeks

```
d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T)
d2 = d1 - σ√T

Delta(Call) = N(d1)
Delta(Put)  = N(d1) - 1
Gamma       = N'(d1) / (S σ √T)
Vega        = S N'(d1) √T / 100      (每 1% IV 变化)
Theta(Call) = [-S N'(d1) σ / (2√T) - rK e^(-rT) N(d2)] / 365   (每日)
Theta(Put)  = [-S N'(d1) σ / (2√T) + rK e^(-rT) N(-d2)] / 365
Rho(Call)   = K T e^(-rT) N(d2) / 100  (每 1% 利率变化)
Rho(Put)    = -K T e^(-rT) N(-d2) / 100
```
- S=现价, K=行权价, T=剩余年(按365日), r=无风险利率(默认0.045), σ=IV
- N()=标准正态 CDF, N'()=标准正态 PDF
- 零波动采用确定性贴现极限：Call=`max(S-K·exp(-rT),0)`，Put=`max(K·exp(-rT)-S,0)`；到期按内在价值。负现价、负行权价、负波动率和非有限输入拒绝。
- 到期或零波动的内在价值折点不可微，`bs_greeks` 明确报错，不将未知敏感度伪装为零；价格本身仍按内在价值计算。
- 默认 T 计算至美股到期日纽约时间 16:00；尚未自动识别特殊结算或提前收市。模型不含股息和提前行权。
- 实现见 `common.bs_greeks()`,已验证(S=K=100,T=1,r=0.05,σ=0.2):
  delta=0.6368, gamma=0.0188, vega=0.3752, theta=-0.0176/日, rho=0.5322

## 7. 行权概率(ITM Probability)

两种方式:
```
BS 闭式解:  P(Call ITM) = N(d2)
           P(Put ITM)  = N(-d2)
Delta 近似: P(ITM) ≈ |delta|
```
- 这是**风险中性概率**,不含风险溢价,与真实世界概率不同
- 实现见 `calc_exercise_prob.py`

## 8. 组合 Greeks 加权

```
组合 Greek = Σ (单股 Greek × 方向 × 合约数量 × 100)
方向: BUY=+1, SELL=-1
```
- 仅汇总同标的；每张标准美股期权对应 100 股。STOCK 腿的数量 1 表示 100 股。
- 实现见 `calc_option_greeks.py`

## 9. 到期损益

```
单腿到期价值 = sign × intrinsic(S, K) × qty × 100
  intrinsic(Call) = max(S - K, 0)
  intrinsic(Put)  = max(K - S, 0)
  sign: BUY=+1, SELL=-1
  100 = 美股期权每张对应股数

组合净成本 = Σ (各腿 last price × sign × qty × 100)
到期损益 = 组合到期价值 - 净成本
盈亏平衡 = 损益曲线过零点的价格
```
- 仅支持同标的、同到期日；成本用各腿 last price 估算(非组合摆盘价)，不含费用或提前行权。
- 在 `S=0`、所有行权价拐点和最右区间斜率上解析计算全局极值和盈亏平衡点；绘图扫描不决定风险上限。零损益区间另用 `break_even_ranges` 表示。
- 实现见 `calc_option_pnl.py`

## 10. 标准策略行权价选择

| 策略 | 行权价选择 |
|---|---|
| ATM | find_atm_strike(chain, 现价) |
| OTM Call | nearest_strike(现价 × (1+otm_pct)) |
| OTM Put | nearest_strike(现价 × (1-otm_pct)) |
| ITM Call | nearest_strike(现价 × (1-otm_pct)) |

默认 otm_pct = 0.05(5%)。先限定 ITM/OTM 方向和严格行权价顺序，再选近邻；标准蝶式要求两翼等宽，无法组成时拒绝生成。实现见 `get_option_strategy.py`。

## 11. 期权结构指标(v0.2+ 新增)

```
跨式成本幅度 = (ATM call 价格 + ATM put 价格) / 现价
跨式到期盈亏平衡 = ATM 行权价 ± 跨式成本(每股)
IV 模型标准差尺度: EM_iv = ATM IV × √T
Risk Reversal(RR)= IV(25Δ Call) - IV(25Δ Put)     (25Δ 合约按 BS delta 定位)
赔付(S) = 100 × [Σ max(S-K,0)·callOI + Σ max(K-S,0)·putOI]
Max Pain = argmin_S 赔付(S)   (标准美股合约、可用 OI 样本)
GEX(K)  = gamma_call×callOI×100×S²×0.01 - gamma_put×putOI×100×S²×0.01
GEX 剖面 = Σ_到期日 Σ_K GEX(K | S 假设价位, sticky-strike IV + BS gamma 重算)
Gamma Flip = GEX 异号交叉的插值价位(取离现价最近,自动扩域至 ±40%)
恰好为零的采样点保留；异号包围的零段取现价在该段上的最近点；同号相切和零尾排除
细粒度 S/R = call/put OI 高斯核密度(带宽=行权价间距)局部极大值 + 抛物线插值
```
- 实现:`calc_expected_move.py` / `calc_risk_reversal.py` / `calc_max_pain.py` /
  `calc_gex.py` / `calc_gamma_profile.py`;交叉验证见 new-modules-map.md
- 跨式成本不是 1σ；IV 标准差尺度依赖模型，不能保证真实覆盖率。成本基于报价样本，未计交易成本。
- GEX 的 Call 正/Put 负来自仓位方向假设，OI 本身不能证明做市商净仓位。当前正负看当前 GEX，翻转方向看交叉两侧符号。
- Max Pain 仅是样本最低赔付价，不预测现价收敛；成交量回退是另一代理统计量。显式非标准合约排除，未知调整合约不可假定受支持。

## 12. 技术指标(v0.3+ 新增)

实现见 `scripts/technical/indicators.py`(纯函数库),关键约定:
- EMA:α=2/(n+1),种子=前 n 个 SMA;MACD=EMA12-EMA26,信号线 EMA9
- RSI/ATR:Wilder 递归平滑;BOLL(20,2):总体标准差(ddof=0)
- KDJ(9,3,3):RSV=(C-L9)/(H9-L9)×100,种子 K=D=50,J=3K-2D
- OBV 斜率:近 20 期最小二乘;量比=最新量/之前5根均量(排除当前根)。缺失量保留为未知。
- 唐奇安展示可含当前根，突破判断只与之前20根比较。Beta 使用真实市场交易日期对齐，零 Beta 有效。
- 52周位置 =(C-低)/(高-低)×100;Beta = cov(标的,市场)/var(市场)(按日期对齐)
- 单元测试约束:单边涨 RSI=100、对称序列 Wilder RSI=50、BOLL vs statistics.pstdev、Beta(2×市场)=2

## 13. v0.4.0 新增模块计算

### 13.1 量价分布 Volume Profile(trade-stats)
```
vol(K) = buy_amount + sell_amount + neutral_amount        # 每价位总量(近5日)
POC    = argmax_K vol(K)                                   # 样本成交量最大的价位
Value Area(70%):
  从 POC 起向"更厚的一侧"贪心扩展 —— 每步比较相邻上/下档的 vol,
  并入较大者,直到累计 ≥ 0.7 × Σvol;VAH/VAL = 区间上下沿
买卖失衡 = Σbuy / Σsell (>1.1 买方占优, <0.9 卖方占优)
位置判断使用接口近5日均价 avgprice: >VAH 或 <VAL 表示在样本价值区间外
支撑/阻力解释是启发式，不证明后续价格反应
```

### 13.2 A/H 溢价统计(ah-premium)
```
rate 含义: ahpremium_rate < 0 = H股折价(如 -0.266 = H 比 A 便宜 26.6%)
zscore = (latest − mean) / pstdev(rates)        # z>0: rate更高；若折价则折价更浅
trend  = mean(后半段) − mean(前半段)             # >0 H相对走强，<0 H相对走弱，=0 持平
```

### 13.3 业务集中度(business-segments)
```
CR1 = max(percent)                 # 第一大分部营收占比
CR2 = sum(top2 percent)            # 前二大分部合计(>70% 单一依赖风险)
```

### 13.4 财务共识 beat/miss(consensus)
```
pct = (actual − estimate) / |estimate| × 100
pct > +0.5 → 超预期; pct < −0.5 → 逊预期; 其间 → 符合; actual 空 → 待公布
estimate=0 → 百分比不可计算，保留 actual-estimate 绝对差，不标为符合0%
```

### 13.5 宏观 surprise(macrodata)
```
surprise = actual − forecast
beat_rate = #{actual > forecast} / #{已发布期数}
```

### 13.6 拆股比例解析(split calendar)
```
正则: (\d+) 股 (合并为|拆分为) (\d+) 股  →  "X→Y(合股/拆股)"
```

### 13.7 多股对比排名(compare)
```
排名方向: 估值类(pe/pb/ps)升序,第 1 名=最低=最优;
          质量类(roe/roa/net_margin/div_yld)降序,第 1 名=最高=最优
best_per_metric = argmin(估值类) / argmax(质量类),跳过空值
```

### 13.8 内部人交易方向(insider-trades)
```
买卖: code='P' 买入，code='S' 卖出；代码优先，无代码时按 BUY/PURCHASE/SELL/SALE 分类
其他: A=授予，M=行权/转换，D=向发行人处置，分别列示且不混入普通买卖净额
净额=Σ普通买入值−Σ普通卖出值；只描述净买入/净卖出，不推断真实交易动机
```

### 13.9 经纪商队列权重(brokers)
```
level_presence(broker) = Σ 出现档位 × 权重;买一档(bids, position=1)权重 2,其余 1
```

### 13.10 quant pine 交叉验证口径
```
需先证明相同标的、周期、起止时间、复权、bar 时间戳及预热窗口。
当前服务端摘要缺少完整对齐元数据，--cross-check 明确返回 skipped 及原因。
JSON 与文本共用结果；过去某次末值接近不能证明任意请求可比。
```

## 14. 评分与数据覆盖

- 异动维度各自封顶 40/30/20/10，直接相加，总上限 100；缺少维度时不输出完整等级。
- 买卖仪表盘方向权重为技术30、估值15、资金20、期权10、分析师15。技术面必须有效，且有效权重至少60；否则不给总分和方向。事件风险单独最多削减偏多方向7分，最低降至50。
- 入场规则以未舍入的风险收益比判断 `RR>=1`，统一使用显示的入场参考价。必要人工条件或数据质量待确认时不能判为纪律通过。
- 评分、阈值和形态属于启发式，尚无样本外收益或胜率校准。
