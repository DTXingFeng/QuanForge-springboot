# 行情、指标、模型研究与展示口径审计

审计日期：2026-11-12。只使用 QF-S 当前工作区、树莓派 SQLite 一致性快照，未读取旧版 QuantForge 记录，未向交易接口下单。此分报告的测试是离线工程验证，不是盈利验证。

## 生产历史数据证据

快照 `.audit-private/qfs-audit-20261112-0805/quanforge.db`，SHA-256 与完整结果见 `data-integrity.json`。复跑：

```powershell
python tools/audit_data_integrity.py .audit-private/qfs-audit-20261112-0805/quanforge.db --history .audit-private/qfs-audit-20261112-0805/history.sqlite --out docs/audit-20261112/data-integrity.json
```

- `kline_1m` 共 221,945 行、9 个 symbol。SQLite quick_check=ok。逐条验证：重复时间戳 0、分钟错位 0、覆盖区间内部缺失分钟 0、非法 OHLCV 0。该观察仅限实际保留区间，不能推出断网期间总无缺失。
- 主要品种各 25,855 条，时间编码按 epoch 毫秒解释为 UTC 2026-08-01 16:32 至 2026-08-19 15:26；HEMI/HYPE/CYS 各约 22,270 条，尾部止于 8 月 17 日。JDBC `LocalDateTime` 存储存在时区解释风险，但 8 小时偏移不能解释数月差距。
- `ai_advice_track` 789 条，时间跨 8 月 19 日至 11 月 12 日，只有 **69/789** 条开仓建议的创建时刻落在对应品种本地 K 线的保留范围内。这还不保证整笔持仓区间都覆盖。因此该表不足以复原绝大多数订单的实时行情路径、MFE/MAE、止损越界和因果收益。
- `KlineHistoryController.download()` 是下载器的唯一调用者；`KlineHistoryService` 无自动调度。它是按需训练/历史管道，不是 Java 真实交易采集总线。Java AI 工具、触发器及 Python 交易脚本直接请求市场数据；不能把历史表陈旧误判为所有交易都使用陈旧行情。
- 对独立重新下载的公共 REST 历史 `history.sqlite` 逐时间戳交叉验证：重叠 **3,178 根**中，**3 根 close、2 根 high** 与原归档不一致；全在原表末尾 2026-08-19 15:26Z。SOL 原 close 81.24，完整历史 81.37；ZEC 547.46→547.92；SNDK 1593.38→1593.0。三者原 open 一致、原 volume 均更低，其余重叠柱 close 匹配。这与原下载器落入当前未完成柱的代码和失败测试一致，构成生产归档中尾柱未定稿的实证；不能由此推定某笔订单一定因此亏损。重叠匹配也不支持整段归档存在统一 8 小时时间错位的假设。

后续公共历史捕获弥补了部分交易窗口缺口；其逐笔覆盖与回放结果由主报告列出。上述69/789仅指原生产归档覆盖，不应误读为补采后的覆盖率。

## 已复现并最小修复

1. **AI 指标与固定上下文/异动触发器使用尚未收盘的柱。** 原 `AiToolRegistry.rawKlines()` 和 `AiAnalysisService.fetchKlines()` 直接反转 API 返回行。在相同输入中，149+ 根价格 100 的已完成柱加一根当前价格 999 的未完成柱，工具原输出 lastPrice=999；固定上下文输入原为 `[99,100,999]`。修复后指标价格=100，固定上下文为 `[99,100]`。模型推理输入也共用已收盘行。
   - 最小修复：共享 `closedKlines()`，按请求开始时间判定柱完成、倒序排序、相同时间戳去重；冲突重复或内部时间缺口拒绝输入，不用缺失分钟当相邻分钟。日/周/月按 UTC 日历处理。额外请求一根以保留原已完成样本数量。
   - 工具增加 `barPolicy=CLOSED_ONLY`、`dataThroughEpochMs`，可区分数据结束时点。此更改不提供整个 AI 多轮会话的原子行情快照。
2. **下载重试不能补较旧的孔洞。** 原代码直接从库内最大时间戳开始，即使请求的 earliest 更早。相同请求原 start 比 earliest 晚三分钟；已在 `market-data-before.txt` 保存失败。修复后扫描调用者明确指定的有界区间，主键重复写入不新增历史实体；端点上限为最后已收盘分钟，拒绝 API 越界/错分钟数据。下载计数改为“校验/写入”，避免把重复覆盖行称作“新增”。此修复只保证下次执行指定区间下载可访问旧缺口，不在生产触发下载，也不保证 API 返回空窗被自动重试。
3. **EMA 历史不足给出 0。** `emaSeries` 原默认零数组让不足 7 根的 EMA7=0。原测试失败 0 vs NaN；修复暖机区初始化 NaN，避免造出可用指标。
4. **训练时间戳单位不明确，训练/在线小时特征不一致。** `train_baseline.py` 与 `train_lgbm.py` 原 SQL `parse_dates=["open_time"]` 对 INTEGER 毫秒未指定单位。使用真实加载路径、3,000 条 SQLite fixture、pandas 3.0.6 复现：相邻真实 1 分钟被解释为 16 小时 40 分钟，首日年份 58553。在线 `model_server.py` 明确 `unit="ms"`。两行修复为 `parse_dates={"open_time":{"unit":"ms"}}` 后两个训练入口均得到 2026 年、1 分钟相邻时间和 UTC 小时 16。未重训、未覆盖现有模型；现有生产模型的训练时 pandas 版本及来源不可由当前代码证明，不能断言其权重必然受影响。
5. **历史校准准确率对 AI 的表述过强。** `train_lgbm.py` 先用未来窗口波动幅度筛选测试样本，随后报告该条件样本准确率。`model_server.py` 将校准准确率回传，原工具再写死“高58%/中54%”，并丢掉 sidecar 的 `inDomain`。已删除固定准确率宣传文字，改成“按未来波动筛选的历史条件样本，不代表实时胜率或扣成本盈利概率”，透传 domain/inDomain。未修改模型参数或分数来美化结果。

## 前后验证

```powershell
.\mvnw.cmd '-Dtest=MarketDataAuditTests' test
python -m unittest discover -s tools -p test_audit_training_timestamps.py
```

Java `MarketDataAuditTests` **6 个测试通过**。原始三个行为先运行得到 3 个失败；fallback 后补独立失败 `[99,100,999]` vs `[99,100]`，再修复通过。其他覆盖乱序/一致重复规范化、缺失分钟拒绝、月线 UTC 日历。日志为 `market-data-before.txt`、`fallback-before.txt`、`market-data-after.txt`。

Python **1 个测试方法、2 个训练入口子场景**：修复前 2 个子场景失败；修复后通过。日志为 `training-time-before.txt`、`training-time-after.txt`。ML 拟合前拦截真实 DataFrame，使用 stub 跳过 sklearn，未进行模型拟合、未连网络。

这些实验收益、回撤、手续费、交易次数均 N/A：没有触发任何交易决策或撮合。可证明数据与指标行为变化，不能转化为修复赚取了多少收益。

## 尚待验证/尚未解决的风险

- **共同快照与过期决策：** agent 的工具每次独立请求，15m/5m触发、模型1m、ticker、风控取价和最终下单之间没有共同 snapshot ID，`dataThroughEpochMs` 只是可观察性改善。快速市场应在提交前校验决策年龄、价格偏移与输入时点，并保留输入摘要。
- **模型评估：** `train_lgbm.py` 的未来波动筛选属于条件评估选择，不能在线预先知道条件是否成立；训练/测试切分没有 horizon purge，边界训练标签会使用测试期价格。`train_baseline.py` 最后 horizon 行比较 NaN 后转成跌标签，不能当有效真值。当前未重训，既有58%等数值不构成前向研究证据。特征 build() 的滚动/shift 本身未发现直接未来特征，但不能用此排除标签边界泄露。
- **策略选择：**仓库有多轮品种/门槛/策略研究脚本，但代码无法证明研究过程使用独立保留样本或记录了全部失败试验。需要冻结前向协议、全部策略臂汇总、成本和置信区间；不能据此量化回测过拟合比例。
- **展示限制：** `HistoryPage.fetchRecords()` 只返回最新 50 条，无 nextPageCursor 翻页，不能作为完整交易账本。成交列表显示 execFee，平仓列表显示交易所 closedPnl；不应把当前一页当全部收益。纸面面板混合后端统计并只显示百分比均幅，不能与资金加权净权益混为一谈。设置页“绝对准确”文字超过可验证证据，交易所平仓值还需要成交/资金账单对账。
- **断线重连：**桥脚本重连没有 REST 回补历史窗口，deque内存状态可混入断网前后不连续观测。行情工具现遇内部缺口拒绝，下载器可在下一次有界下载修复缺口；两者均不等于持续采集的自动补齐系统。
- **时区迁移：**历史实体用 LocalDateTime、JDBC整数与 Python UTC特征混合。没有在此次审计中迁移或改写真实历史时间戳；部署机器时区变更应先以捕获的原始 Bybit 时间戳逐根对账。

结论：已确认输入数据完整性缺陷并修复主要 Java 支路，保存前后失败/通过证据；没有证据把真实亏损的某个百分比归因于这些缺陷。当前归档不足以验证绝大多数实际订单的行情路径，模型历史准确率也不足以证明策略净优势。
