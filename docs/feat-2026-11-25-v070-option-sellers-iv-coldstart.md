# 2026-11-25 v0.7.0 更新记录（PR-3：期权卖方策略 / Delta 选腿 / 内联损益 + IV 自动采集与冷启动代理）

开发基准：`300d601`（main，0.6.7，PR #9 已合并）；CLI 实测版本：`longbridge 0.32.0`。

## 1. 期权卖方策略 + 目标 Delta 选腿 + 流动性与内联损益（`scripts/quote/get_option_strategy.py`、`calc_option_pnl.py`）

- **新增 3 种定义风险（Defined-Risk）期权卖方策略**（策略总数 `8 → 11`）：
  - `BULL_PUT_SPREAD`：卖出近价 OTM Put + 买入远价保护 Put（温和看多/震荡收租）；
  - `BEAR_CALL_SPREAD`：卖出近价 OTM Call + 买入远价保护 Call（温和看空/逢高收租）；
  - `IRON_CONDOR`：同时卖出下方 Put 信用价差与上方 Call 信用价差（区间震荡赚时间价值衰减）。
- **新增 `--delta` 与 `--width` 选腿模式**：
  - `--delta <|Δ|>`（支持 `0.02 ~ 0.49`）：直接基于期权链 `call_iv`/`put_iv` 通过本地 BS 公式（零额外 CLI 开销）定位最接近目标 Delta 的短腿/核心腿；
  - `--width <美元宽度>`：精确控制信用价差/铁鹰/垂直价差/蝶式的保护翼距离（未传时按 `price × otm_pct` 选最近档）。
- **新增 `--check-liquidity` 与 `--with-pnl` 一站式评估**：
  - `--check-liquidity`：单次批量调用 `get_option_contract_metrics` 拉取选中期权腿的真实未平仓量（`OI`），`OI < 100` 或缺失时显式预警；
  - `--with-pnl`：`calc_option_pnl.analyze_pnl()` 新增 `quiet=True` 与预取链透传，在 `get_option_strategy.py` 内直接输出净权利金收入/支出、最大盈利、最大亏损、风险回报率（ROR%）、基于盈亏平衡区间的 BS 风险中性到期胜率（POP%）与组合 BS Greeks。

## 2. IV 机会式自动记录、批量自选采集与 1 年 HV30 冷启动代理（`scripts/quote/get_iv_history.py`、`calc_iv_rank.py`、`calc_iv_percentile.py`）

- **日常问股无感自动记录（`maybe_record_daily_iv`）**：
  - 在 [`analyze_buy_sell.py`](../scripts/decision/analyze_buy_sell.py)、[`get_option_volatility.py`](../scripts/quote/get_option_volatility.py)、[`analyze_iv_crush.py`](../scripts/quote/analyze_iv_crush.py) 与 [`get_option_strategy.py`](../scripts/quote/get_option_strategy.py) 查询美股 `.US` 正股时，若当天恒定 30 日 ATM IV 尚未记录，则复用当前进程缓存静默追加至本地 JSON（当天已记录则 `< 1ms` 跳过；单测默认隔离，支持 `LBR_AUTO_IV_RECORD=0` 关闭及 `LBR_IV_HISTORY_DIR` 自定义存储目录）。
- **多标的 / 自选 / 持仓一键批量采集**：
  - `get_iv_history.py` 新增多标的位置参数与 `--watchlist` / `--group` / `--positions`，自动过滤美股正股并预热 `get_batch_quotes`，输出汇总表与日环比变化。
- **1 年滚动 HV30 冷启动过渡代理与断档提示**：
  - 当本地可比恒定 30 日 IV 样本不足 `min_points`（默认 `20` 天）时，`calc_iv_rank.py` 与 `calc_iv_percentile.py` 默认拉取过去 1 年日 K 线计算滚动 30 日实现波动率 `HV30` 序列，输出 `rank_basis="hv_52w_proxy"` 的过渡分位、当前 `HV30` 及 `VRP = ATM_IV - HV30`（保持 `iv_rank=None` / `iv_percentile=None`，不冒充真实历史 IV；传 `--strict` 可保持原严格报错）。
  - 积累满 20 天后自动恢复 `rank_basis="iv_history"`；若存在超过 14 天的采集断档或近期密度过低，输出 `coverage_warning` 并附带 `hv_proxy` 交叉验证。

## 验证

- 新增 [`tests/test_fixes_v070.py`](../tests/test_fixes_v070.py) 并验证全量单元测试、Python 3.8 AST 检查、`git diff --check`、`SKILL.md` frontmatter 长度校验及 `longbridge 0.32.0` 美股实盘复检（详见 PR #10 说明）。
