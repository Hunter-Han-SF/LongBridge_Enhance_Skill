# 2026-11-25 v0.6.7 更新记录（PR-2：进程内缓存提速 + 自选股/持仓扫描器 + 风险定仓计算器）

开发基准：`326201c`（main，0.6.6，PR #8 已合并）；CLI 实测版本：`longbridge 0.32.0`。

## 1. 线程安全限频 + 进程内只读 CLI TTL 缓存（`scripts/common.py`）

- **并发节流锁**：`_throttle()` 改用 `_THROTTLE_LOCK` 互斥预约时间槽，支持 `ThreadPoolExecutor` 并发扫描时稳定保持 `≤ 9 req/s`，不再发生并发抢占触发 429 限频。
- **进程内只读 TTL 缓存**：`run_cli()` 为只读查询命令（`quote`、`kline`、`option`、`static`、`valuation`、`institution-rating`、`forecast-eps`、`financial-report`、`dividend`、`finance-calendar`、`market-temp`、`rank`、`industry-*`、`short-*`、`capital`、`news`、`watchlist` 只读/`show`、`positions`、`assets`）提供进程内短生命周期缓存（默认 `TTL = 15s`，可通过环境变量 `LBR_CACHE_TTL=0` 关闭或传 `use_cache=False` 跳过），返回值始终经 `copy.deepcopy` 隔离修改。
- **K 线超集尾切片复用 + 批量报价缓存回填**：`kline` 同一 `(symbol, period, adjust, session)` 已缓存 `count >= req_count` 时，后续短窗口请求（如仪表盘内 `260 → 30` 根）直接零 CLI 调用切片复用；`get_batch_quotes()` 在一次批量拉取后自动把各标的行情回填进单票 `"quote"` 缓存。

## 2. 只读自选 / 持仓 / 账户购买力封装（`scripts/common.py`）

- 新增只读封装：`is_equity_symbol()`（过滤期权合约、`.INDEX`、加密 `.HAS` 与港股 5 位涡轮牛熊证）、`get_watchlist_groups()`、`get_stock_positions()`、`get_account_assets()`（兼容 `v0.32.0` 数组响应）、`estimate_max_purchase_qty()`（兼容 `v0.32.0` 键值列表响应）。所有接口严格只读，无任何下单/改单能力。

## 3. 自选股/持仓批量扫描器（`scripts/decision/scan_watchlist.py`）

- 新增独立扫描引擎 `scripts/decision/scan_watchlist.py`，支持三种标的水池：显式传入股票代码、只读自选股（`--watchlist` / `--group <分组>`）、只读当前持仓（`--positions`，自动带出成本浮盈率）。
- 流程采用「1 次批量 `quote` 预热 + 每市场 1 次大盘 Regime + 并发受控工人线程」架构：
  - `--fast`（默认）：扫描技术分、趋势背景、28 条军规买点（`B1-B9`）/阻断（`D/U`）、止损距离、盈亏比、财报距离与盘前跌破止损告警；
  - `--full`：叠加完整六维买卖决策仪表盘评分（复用缓存零冗余 K 线/quote 调用）。
- 默认按 `actionable`（有买点且无阻断优先 → 评分 → 盈亏比）排序，支持 `--only-setups`、`--sort`、`--capital` / `--use-account`。

## 4. 风险定仓计算器（`scripts/decision/check_entry_rules.py`）

- 新增纯函数 `calc_position_sizing()` 及命令行参数 `--capital`、`--use-account`、`--risk-pct`（默认 `1.0%`）、`--max-pos-pct`（默认 `20.0%`）：
  $$\text{Shares} = \left\lfloor \frac{\min(\lfloor \text{Capital} \times \text{Risk\%} / (\text{Entry} - \text{Stop}) \rfloor,\ \lfloor \text{Capital} \times \text{MaxPos\%} / \text{Entry} \rfloor)}{\text{LotSize}} \right\rfloor \times \text{LotSize}$$
- 非美股自动按 `static.lot_size` 向下取整手；启用 `--use-account` 时同步核对只读 `max-qty` 现金/融资可买上限并在不足或盘前跌破止损时输出风险提示。

## 验证

- 新增 [`tests/test_fixes_v067.py`](../tests/test_fixes_v067.py) 并更新 [`tests/test_dirty_fuzz_v056.py`](../tests/test_dirty_fuzz_v056.py)。
- 全量单元测试、Python 3.8 AST 检查、`SKILL.md` frontmatter 长度校验及 `longbridge 0.32.0` 美股实盘复检见 PR 说明。
