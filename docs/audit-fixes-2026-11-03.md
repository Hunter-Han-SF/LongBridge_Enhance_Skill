# 2026-11-03 审计修复记录（0.6.0）

审计基准：`7b35046`。本地分支：`fix/audit-20261103`。修复范围为原审计的 27 项问题、附加 A–I，以及独立复核发现的边界问题。代码保持标准库实现，未调用证券账户或真实行情；变更通过该分支向 main 提交 PR。

## 原审计逐项处理

| 编号 | 修复结果 | 主要实现 |
|---|---|---|
| 01 | 异动维度按 40/30/20/10 直接相加，满分可达 100；缺失维度不给完整等级 | `scripts/market/calc_anomaly_score.py` |
| 02 | 以零价、行权价拐点、右尾斜率解析极值和盈亏平衡；采样仅用于画图 | `scripts/quote/calc_option_pnl.py` |
| 03 | 当前 GEX 由当前符号决定；翻转按两侧异号判断，排除相切和零尾部 | `scripts/quote/calc_gamma_profile.py`、`calc_gex.py` |
| 04 | 技术面必须有效且方向覆盖权重至少 60；事件仅单独削弱偏多信号 | `scripts/decision/analyze_buy_sell.py` |
| 05 | 止损距离和 RR 统一使用输出中的入场参考价，明确收盘回退 | `scripts/decision/check_entry_rules.py` |
| 06 | 必要人工闸门、B0 或关键数据待确认时，不能输出纪律通过 | 同上 |
| 07 | 分开跨式成本幅度、K±成本的到期盈亏平衡、IV 模型标准差尺度 | `scripts/quote/calc_expected_move.py` |
| 08 | 标准美股合约赔付乘 100；排除显式非标准链记录，说明样本/代理限制 | `scripts/quote/calc_max_pain.py`、`scripts/common.py` |
| 09 | 价差两腿严格分离、方向受约束；标准蝶式等宽，无法构造即报错 | `scripts/quote/get_option_strategy.py` |
| 10 | 本次采集失败时不把旧 IV 当当前；校验日期、排序去重、排除未来记录 | `get_iv_history.py`、`calc_iv_rank.py`、`calc_iv_percentile.py` |
| 11 | BS 零波动使用贴现内在价值；非法输入拒绝；不可微折点不伪造 Greeks | `scripts/common.py` |
| 12 | TTM 锚定市场估值日，排除未来除息；增长比较最近两个已结束自然年的已有记录，股息率检查币种 | `scripts/fundamental/get_dividend_quality.py` |
| 13 | 结构化股息优先，兼容 `USD 0.26/share` 和 `0.26 USD` | `scripts/common.py` |
| 14 | 精确科目匹配，跨表比值要求期间可比；亏损不产生现金转化绿灯，增加覆盖门槛 | `scripts/fundamental/get_financial_health.py` |
| 15 | 修正 A/H 正 z 的方向，区分持平和不足样本 | `scripts/market/get_ah_premium.py` |
| 16 | P/S 为普通买卖；A/M/D 分别列示，不把授予或行权当作主动看多 | `scripts/fundamental/get_insider_trades.py` |
| 17 | Tick 方向仅作为价格方向压力代理；排序按有效时间，显示未分类比例，缺价格安全输出 | `scripts/intraday/get_trade_flow.py` |
| 18 | 缺失沽空率保留未知；最近窗口与历史窗口覆盖不足不判断降温 | `scripts/flow/get_short_sale.py` |
| 19 | VWAP 占比分母只含有效价格/VWAP 配对，同时输出覆盖；30 分钟按时间定位 | `scripts/intraday/get_vwap_analysis.py` |
| 20 | 预期零时百分比未知，保留绝对差，不再输出“符合 +0%” | `scripts/fundamental/get_consensus.py` |
| 21 | 唐奇安突破使用之前 20 根，展示通道可以含当日 | `scripts/technical/calc_indicators.py`、`calc_technical_score.py` |
| 22 | RS 以真实市场日期对齐并去重，缺日期拒绝；Beta=0 保留 | `scripts/technical/calc_relative_strength.py` |
| 23 | RR 闸门比较未舍入值，`.996` 不再通过 `>=1` | `scripts/decision/check_entry_rules.py` |
| 24 | B8 自动板块判断只配对同日股票突破，历史或未知日期保留人工确认 | 同上 |
| 25 | quant 历史请求以 end 推 start，外部策略按内容识别；缺对齐元数据明确跳过交叉验证 | `scripts/technical/run_quant_indicator.py` |
| 26 | 数值入口拒绝 bool/NaN/Infinity，严格 JSON 将非有限结果输出 null | `scripts/common.py` |
| 27 | 仅转换已知数值字段，保留 CUSIP/CIK/代码/日期等标识字符串 | 同上 |

## 附加一致性问题

- A/B：量比统一为当根除以前五根均量；缺量不等于零量；ATR=0 保留，无有效成交量不产生 MFI 健康加分。
- C：统一市场日期与时区；标准美股期限默认算到纽约 16:00，同日收盘后的到期合约不再作为默认最近到期日。
- D：IV 改为恒定 30 日期限，按两侧到期日总方差插值，无两侧数据不外推。历史原始记录保留，非可比样本不混算。
- E/F：GEX 明示仓位方向假设，OI 密度峰不代表精确真实支撑；Max Pain 明示样本最低赔付点，不宣称价格引力。
- G：历史 IV 急降只比较相邻自然日可比样本，不把它直接解释为已验证的财报效应。
- H：评分、阈值和形态统一作为启发式描述，不声称已验证的样本外高胜率。
- I：显式零止损上限保留，非法 lookback/目标价等拒绝；“历史新高”改为回看区间新高；中英文 README、SKILL 和公式参考同步至 0.6.0，移除过时固定测试数。

## 接口和兼容性变化

1. 资金流默认保留来源单位，`amount_unit=source_unit`、`unit_verified=false`，不再自动乘一万。核实后可设置 `LBR_CAPITAL_SCALE` 为换算倍率；它记录操作者配置，不能视为程序已验证真实接口。
2. `LBR_CAPITAL_FLOW_MODE` 可设 `cumulative` 或 `incremental`；默认 `unknown` 不计算分钟峰值或日累计。累计模式只对严格相邻 60 秒观测产生 `minute_delta`；长间隔另给 `interval_delta` 和 `interval_seconds`。计算保留精度，小额来源值不会先舍入成零。
3. 旧 IV 缓存不删除；其非恒定期限样本不再参与 Rank/Percentile，因而升级后可能暂时显示可比样本不足。统计窗口是全部本地可比记录，并非固定一年。采集时间不等于上游报价已确认实时。
4. 多腿 Greeks 限制为同标的并校验类型、动作和数量；期权按标准 100 股合约。明确调整合约不可混算，未提供交割规格的合约无法由本地保证支持。
5. `--cross-check` 现在会明确返回跳过原因，直到服务端可提供足以对齐周期、时间、复权和预热窗口的元数据。
6. 入场结果新增数据质量和必要确认信息；实时价缺失、最新价格 K 线无效或近期量能不充分时不能判为纪律通过。`--demo --json` 输出与选项一致的严格 JSON。

## 独立复核追加项

已处理 BS 不可微折点、资金源值提前舍入、数值时间戳大单文本、同日收盘后到期选择、GEX 网格恰为零点的穿越定位及非默认扫描范围的扩域遗漏；对应回归纳入 `tests/test_audit_*.py`。

## 验证与边界

四个新增专项测试文件覆盖独立预期值、缺失与有效值混合、日期、文本/JSON 一致性及上述边界。旧测试中固定错误语义的断言已调整，例如人工闸门未确认不能通过、授予/行权不计普通买入、零行权价使用正确极限。

最终验证（Python 3.13.15）：

- `python -B -m unittest discover -s tests`：PR准备阶段复跑310项全部通过，26.837秒；较审计基线增加78项专项回归。
- 72 个 argparse 命令 `--help` 全部成功。
- `check_entry_rules.py --demo` 及 `--demo --json` 均成功；JSON 严格解析，包含 3 个合成场景。
- 74 个 Python 源文件通过 Python 3.8 语法模式解析；`git diff --check` 通过。
- 独立复核未发现仍需阻断交付的计算问题；复核人员另行运行公共层、市场数据和期权专项共 55 项并通过。
- SKILL description 正文为 872 字符（含 YAML 末尾换行为 873），低于该文件约定的 1024 字符上限。

本次没有收益回测、真实账户/行情契约验证或 Python 3.8 解释器运行验证。标准到期时间未自动识别提前收市/特殊结算，相关假设在公式文档中明示。

## 文档同步范围

本次同步中英文 README、SKILL、三份 references、三份分域记录、本审计记录和实施计划。补正 Percentile 排除本次观测的分母、原生 Greeks 优先路径、内部人交易只描述买卖事实、IV急降未关联财报以及方向评分/事件风险分离；历史版本段落注明被0.6.0替代的行为。

文档检查覆盖11份文件、25个本地链接和178条Python命令示例：路径存在、代码围栏闭合，示例选项均存在于对应脚本的参数定义中。SKILL登录元数据与CLI认证前提统一；离线演示仍无需登录。命令中的固定到期日、行权价与历史样本已标为格式或历史观测示例。

股息增长使用最近两个已结束自然年的已收到记录，不能保证接口历史完整。财务跨表比值检查期间、年份及已提供的报告类型，并沿用报表来源单位；本地不独立核验货币或作外汇换算。
