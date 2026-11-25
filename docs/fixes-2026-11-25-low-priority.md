# 2026-11-25 低优先级修复记录（0.6.4）

修复基准：`ab461cd`（main，0.6.3，PR #4 已合并）。分支：`fix/audit-low-20261125`。

本轮处理第六轮审计的低优先级各小项：GEX gamma 来源、组合 Greeks 的 `theta_source` 传导、
A/H 溢价日期时区、估值同行排名、Put/Call 墙位置标注、Gamma 剖面去重间距、美股半日市 T、
市场温度档位统一、异动榜涨跌幅百分比格式化；同时复核了「唐奇安突破信号」现状。

## 1. 唐奇安突破信号永不触发（核实已在此前修复，未改动）

### 现状核实

`scripts/technical/calc_indicators.py` 在 `compute_all` 中分别计算含当前根的 `dc = donchian(highs, lows, 20)` 与前 20 根的 `prior_dc = donchian(highs[:-1], lows[:-1], 20)`，传给 `_detect_signals` 的是 `prior_dc`；`scripts/technical/calc_technical_score.py` 读取的也是 `donchian20_prior`；`tests/test_audit_decisions.py` 与本轮 `tests/test_fixes_v064.py` 均验证新高/新低可正常触发信号。本次未改动相关代码。

## 2. `calc_gex.py` 优先使用服务端 3 位小数 gamma

### 问题

`calc-index` 返回的原生 `gamma` 只有 3 位小数（如 `0.046`）。此前 `calc_gex.py` 在 OI 模式下只要服务端 `gamma` 非 `None` 就直接采用，有持仓的虚值腿常被舍入为 `0.000`，同时造成总量误差。

### 实证与修复

- `_gamma` 改为优先使用合约自带 IV（`v["call_iv"]` / `v["put_iv"]`）按 Black-Scholes 重算 gamma（来源记为 `bs_contract_iv`），缺失时使用 chain 同侧 IV 重算（`bs_chain_iv`），两者均缺失时才用服务端原生 `gamma` 兜底（`native`），均无则记 `none`。
- JSON 输出将 `native_gamma_used` 替换为 `gamma_sources` 字典统计；文本「gamma 来源」列出非零来源计数。
- 实盘复检（`AAPL.US --date 2026-11-27`）：`gamma 来源: BS gamma(合约IV) 96 条`。

### 边界

成交量回退分支原本已全用 chain IV 的 BS 计算，未改动。服务端原生 gamma 仅在合约与 chain 均无有效 IV 时才会启用。

## 3. 组合 Greeks 未传导 `theta_source`

### 问题

`get_option_quote.py` 在服务端 `theta` 为死值（如 `-0.001`）且无法用 BS 补算时，仅将 `theta_source` 标为 `dead_zero`，`greeks["theta"]` 仍保留原值。`calc_option_greeks.py` 未检查 `theta_source`，卖出 10 张死值腿会被加权成 `-1 × 10 × 100 × (-0.001) = +1.00/日`，解读为「时间衰减有利」。

### 实证与修复

- 实盘（2026-11-25，AAPL 2026-12-04 420.0 PUT 零 IV 腿，10 张卖出）：修复后明细显示 `theta=N/A(死值)`，组合计 `theta = N/A`，解读为 `theta 无有效数据(1 条腿为服务端死值,无法补算)`。
- 期权腿 `theta_source` 为 `dead_zero` 或 `None` 时，明细 `theta` 置 `None`、不计入 `totals["theta"]`；正股腿 `theta_source` 记为 `"n/a"`。
- 任一腿无效时，`portfolio_greeks["theta"]` 置 `None`，JSON 新增 `theta_valid: false` 与 `theta_invalid_legs`；存在 `bs_backfill` 腿时新增 `theta_backfilled_legs` 计数。

### 边界

只要组合中存在任意一条无法补算的 `dead_zero` 腿，整组 `theta` 即置为 `None`，不做部分腿求和以免误导。

## 4. A/H 溢价日期按 UTC 换算导致提前一天（出现周日）

### 问题与实证

港股/A 股 A/H 溢价 K 线时间戳对应港股当地 00:00（即前一日 UTC 16:00）。如实盘 `longbridge ah-premium 939.HK` 返回 `1795363200`（UTC `2026-11-22 16:00`，周日），换算成港股时间实际为 `2026-11-23 00:00`（周一）。旧 `_ts_to_date` 用 UTC 格式化，表格出现周日日期。

### 修复

将 `_ts_to_date` 替换为 `_ts_label(ts, intraday=False)`：统一按 `market_now("HK", ...)` 格式化为港股当地时间（日线 `%Y-%m-%d`、分时 `%m-%d %H:%M`，兼容毫秒时间戳），并在 JSON `klines` 每条记录附带 `date` 字段。实盘 `939.HK --count 10` 复检日期为 `2026-11-12` 至 `2026-11-25`，无周六/周日。

## 5. 估值同行排名误用 5 条预览充当全行业排名

### 问题与实证

`longbridge valuation AAPL.US` 的 `peers.pe.list` 只返回 5 条预览样本（且其 `industry_median` 为 `0.74`），旧脚本据此输出「在同行中排第 1/5」。同期 `longbridge industry-valuation dist AAPL.US` 返回完整行业统计：`pe` 为 `rank_index=19, rank_total=19, ranking=1, median=24.3855`（`ps` 为 `34/40`）。

### 修复

`get_valuation_percentile.py` 补充调用 `get_industry_valuation_dist(symbol)`：
- 有 `dist` 时，`peers.target_rank` / `total_peers` / `industry_median` 取 `dist` 的 `rank_index` / `rank_total` / `median`，新增 `rank_basis="industry-valuation dist(全行业)"` 与 `industry_rank` 明细；`peers.list` 保留作预览并新增 `preview_count` 与 `preview_industry_median_raw`（不采信）。
- 无 `dist` 时，`target_rank` 与 `total_peers` 置 `None`（`rank_basis="unavailable"`），文本明示「完整行业排名不可得;预览 N 家不作排名」。
- 实盘 `AAPL.US` 复检：文本输出「同行预览(服务端仅返回 5 家,非完整行业,PE)」与「AAPL PE 行业内由低到高第 19/19(分位 100.0%,行业中位 24.39)」。

## 6. Put/Call 墙在非价外一侧仍标「下方支撑」/「上方阻力」

### 修复

- `scripts/quote/get_option_oi.py`：Put 墙优先在 `strike <= price` 中取最大 OI（无数据时回退全链），Call 墙优先在 `strike >= price` 中取最大 OI；位置标签按实际相对现价位置生成（价上 Put 标「位于现价上方 x%,非下方支撑」，价下 Call 标「位于现价下方 x%,非上方阻力」，平价标「ATM」），JSON 的 `put_oi_wall` / `call_oi_wall` 新增 `position` 字段。
- `scripts/quote/get_put_call_wall.py`：回退到全链导致 Put 墙高于现价或 Call 墙低于现价时，「预计区间」改用 `_wall_label` 描述并打印 ⚠️ 回退提示。

## 7. Gamma 剖面 S/R 去重使用绝对间距 `2.0`

### 修复

`scripts/quote/calc_gamma_profile.py` 的 `_density` 返回自适应核带宽 `h`（行权价间距中位数，空链取 `1.0`），`_peaks` 改用 `abs(px - s) > min_sep`（`min_sep = h`）替代硬编码 `2.0`，使 0.5/1.0 间距标的不致丢峰，高价大间距标的也不会过密聚峰。

## 8. 美股半日市 `T` 仍按 16:00 ET 收盘推算

### 问题与修复

`common.days_to_years` 原固定按 16:00 ET 计算剩余年化时间，导致感恩节次日等 13:00 ET 提前收盘日临近午盘时 `T` 被高估 3 小时（例如 12:30 ET 剩 0.5 小时却按 3.5 小时计，高估 7 倍）。

- `scripts/common.py` 新增 `us_early_close(d: date) -> bool`（按 NYSE/Cboe 规则覆盖感恩节次日、周一至周四的 12-24 与 07-03；交易所临时调整以日历为准）。
- `days_to_years` 与 `is_bar_in_progress` 在 `us_early_close` 为真时使用 `13:00 ET` 收盘。

## 9. 市场温度档位在两脚本间不一致

### 问题与修复

`get_market_temp.py` 使用 `70/50/30` 四档，`daily_briefing.py` 使用 `60/40` 三档（且 `None` 误回退「温和」）。

- `scripts/common.py` 新增 `market_temp_label(temp)`，统一使用 `>=70` `🔥 偏热(贪婪)` / `>=50` `🌡️ 偏暖` / `>=30` `❄️ 偏凉` / `<30` `🥶 偏冷(恐惧)`，`None` 返回 `""`。
- 两脚本的 `_temp_emoji` 均委托给 `common.market_temp_label`；更新 `tests/test_fixes_v055.py` 中对应边界断言。
- 实盘复检（2026-11-25，US 温度 `39.0`）：两脚本均输出 `❄️ 偏凉`。

## 10. 异动榜涨跌幅原样打印小数

### 问题与实证

`longbridge top-movers` 返回的 `stock.change` 为分数形式（实盘 `CRCL.US` 为 `"-0.0831"`），旧脚本直接输出 `(-0.0831)`。

### 修复

`scripts/market/get_top_movers.py` 新增 `change_pct = round(to_float(change) * 100, 2)`，文本格式化为 `(-8.31%)`；价格前缀 `$` 仅对 `.US` 标的添加。实盘 `CRCL.US` 复检显示 `$47.72 (-8.31%)`。

## 验证

- 新增 `tests/test_fixes_v064.py`（13 项回归用例，覆盖上述全部 10 项）。
- 全量单元测试：`python -B -X utf8 -m unittest discover -s tests -t .` → 409 项通过（OK）。
- Python 3.8 语法解析：`ast.parse(..., feature_version=(3, 8))` 遍历 `scripts/**/*.py` 全部通过；`git diff --check` 无空白或冲突问题。
- 实盘复检（2026-11-25，美东夜盘时段）：`get_ah_premium.py 939.HK`、`get_top_movers.py --market US --count 3`、`get_valuation_percentile.py AAPL.US`、`get_market_temp.py US`、`daily_briefing.py --market US --no-pc`、`calc_gex.py AAPL.US --date 2026-11-27`、`get_option_oi.py AAPL.US --date 2026-11-27`、`calc_option_greeks.py`（2026-12-04 420.0 PUT 死值腿）。

## 文档同步

`SKILL.md`（版本号升级为 `0.6.4`、更新修复摘要、已知限制及 GEX/估值/半日市说明；`description` 未改动）、`README.md`、`README.zh-CN.md`、`references/calc-formulas.md`、`references/new-modules-map.md`、`references/capability-map.md`。
