# B 档计算公式参考

本 skill 的 B 档能力用到的数学公式。所有公式实现见 `scripts/common.py`。

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
- 需历史 IV 序列(本地累积)
- 实现见 `calc_iv_rank.py`

## 4. IV Percentile

```
IV Percentile = (历史中 IV < 当前IV 的天数 / 总天数) × 100
```
- 对异常值不敏感(用占比而非极差)
- 需历史 IV 序列(本地累积)
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
组合 Greek = Σ (单腿 Greek × 方向 × 数量)
方向: BUY=+1, SELL=-1
```
- 仅支持同标的同到期日
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
- 成本用各腿 last price 估算(非组合摆盘价)
- 实现见 `calc_option_pnl.py`

## 10. 标准策略行权价选择

| 策略 | 行权价选择 |
|---|---|
| ATM | find_atm_strike(chain, 现价) |
| OTM Call | nearest_strike(现价 × (1+otm_pct)) |
| OTM Put | nearest_strike(现价 × (1-otm_pct)) |
| ITM Call | nearest_strike(现价 × (1-otm_pct)) |

默认 otm_pct = 0.05(5%)。实现见 `get_option_strategy.py`。
