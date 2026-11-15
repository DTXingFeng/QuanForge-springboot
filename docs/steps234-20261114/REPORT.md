# 第 2、3、4 步交付与准入状态

日期：2026-11-14，Asia/Hong_Kong。工作区为当前 QF-S Spring Boot 项目。所有修复在本地；树莓派只执行只读查询及创建取证副本，未部署、重启、改凭证或发单。

## 结论与边界

| 工作 | 已完成的可验证成果 | 仍未通过的门槛 |
| --- | --- | --- |
| 2. 逐笔净账 | Decimal 事件账本、精确订单关联、1176 条新增资金流水的余额链核对；Java 新增执行观察日志 | 历史退出订单/资金费与每个策略的完整归属仍缺；全账户 NAV、全成本逐笔净收益不能认证 |
| 3. 数据与故障 | 复现并修复 Java 过期行情、非法 OHLC/错位时间戳；隔离 PAPER 使用冻结输入摘要、决策过期校验、状态原子提交；10 类故障场景 | Java AI、多工具、模型 sidecar 与执行的同一行情快照尚未闭环；生产保护单、停机接管及跨进程退出命令仍未现场验收 |
| 4. 单策略前向 PAPER | 固定 BTCUSDT、规则和成本假设；完成真实公开行情预热及两次有界运行，取得 6 个报价、1 个新闭合柱及其信号记录 | 0 笔入场、观察时间极短，不能评估优势；资金费仍未知，完整净值不发布；未安装后台任务 |

因此，这次交付使离线研究和本地 PAPER 可以继续检验，但没有把上述三个阶段全部标为交易所自动 Demo 准入通过。

## 2. 真实资金流水与订单归属

新增工具：`tools/audit_net_ledger.py`、`tools/audit_cashflows.py`，共用 `tools/verified_paper.py` 的不可变事件存储。所有原始 JSON/SQLite 位于 `.audit-private/steps234-20261114/`，未加入 Git；公开交付只有汇总和审计关联表。

### 历史平仓报告口径

[net-ledger-summary.json](net-ledger-summary.json) 对原取证集重复导入：1139 条执行、522 条平仓，精确金额保留小数，不靠浮点四舍五入匹配。

- 平仓接口报告净额：**-174.78388015 USDT**。
- 这些平仓行列出的开仓费 67.18036788、平仓费 87.66087086，合计 154.84123874 USDT；不再从报告净额里重复扣除。
- 431 条 Java Demo 跟踪中，411 条可按唯一入场 orderId 找到入场费用；这不是 411 笔完整平仓归属。旧报告的 409 是已入场筛选口径，本次 411 未限定 entered_at，不能视为新增两笔完整交易。
- [net-ledger-tracks.csv](net-ledger-tracks.csv) 保留入场告警理由、触发原因、入场费用证据和缺失项。所有完整逐笔净额仍为空，不把不明退出、资金费和缺失成本填成零。

### 本次新增资金流水证据

经树莓派现有服务的 GET 代理读取同一单一配置凭证，逐请求校验 DEMO 模式。覆盖 2026-08-19 00:00 至 2026-10-27 23:59:59.999 UTC 的 linear 流水，按不超过 7 天分窗、每页 50 条；首周达到原定 5 页上限后单独续取，最多额外 10 页，实际补齐。初始截断清单也保留。

仅取 linear 流水时发现 4 处余额缺口；随后在对应前后交易时间窗查询不带 category 的 USDT 流水，各窗口均完整，找到 **2 笔转入、2 笔转出**：+200、-6.8、+50000、-49855，净流入 **338.20 USDT**。没有操作这些转账。

[cashflow-reconciliation.json](cashflow-reconciliation.json)：

| 新增流水口径 | USDT |
| --- | ---: |
| 去重记录 | 1176 条：1082 TRADE、90 SETTLEMENT、4 TRANSFER |
| 最早交易前余额，由该笔 after balance - change 推得 | 6.55990760 |
| 最后记录余额 | 170.46657410 |
| 记录余额增加 | 163.90666650 |
| 转入/转出净额 | +338.20000000 |
| 排除转入/转出的记录净变动 | **-174.29333350** |
| 交易价差现金流 | -17.49641700 |
| 交易手续费 | -155.17534257 |
| 资金费净支出 | -1.62157393 |
| 逐行公式异常 / 余额链缺口 / 链残差 | **0 / 0 / 0** |

同一毫秒的多条流水按 before/after 余额连接，不按 UUID 猜先后。转入转出解释了“余额变多而交易仍亏损”，也证明不能用初始虚拟资金直接除当前余额计算交易收益率。以上是捕获流水的余额链闭合，**不是整个账户全部产品活动、盯市净值和收益率的完整认证**。

两个亏损数字的样本范围不同：新增流水包含更早的交易/资金费及更多执行。若仅取 `tradeId == 旧execId` 的 1139 条精确交集：价差现金流 -18.308442、手续费 -154.80584569、资金费 -1.63419941，余额净变动 -174.74848710。它仍不是“已平仓交易净额”，禁止与 -174.78388015 混成同一口径。完整摘要保存交集值，未选择更好看的结果替换旧报告。

本次还读取当前钱包及最近一周流水，后者为空；当前钱包快照不能替代历史起点和全账户现金流。没有据此给出策略致亏比例。

### Java 观察事件

`ExecutionJournal` 使用现有 JDBC/SQLite，追加 `execution_event`。已接入入场意图、下单 ACK、未知结果、订单观察、TTL 退出意图、保护单 ACK、保护调整和旧结算估计。记录品种、方向、状态、订单身份、止损止盈及首次观察时间；不覆盖旧止损记录。单独测试验证重建后可读取、同一观察重复写入不重复计数。

这些是观察日志：ACK 不算成交，保护调整 ACK 不证明交易所实际生效时点；它还不是事务 outbox，部分数据库写入失败时会明确报错但继续旧仓保护。不能把日志没有某事件当作交易所一定没发生该事件。原 `result_pct` 仍不属于可靠全成本净账，日志中明确标记 `SETTLED_ESTIMATE`。

## 3. 已复现的行情错误与实验

[market-before.txt](market-before.txt) 中两个用例在修复前实际失败：连续但落后多根的旧柱被接受；错位时间戳和 close 超出 high/low 的数据被接受。修复作用于 `AiToolRegistry.closedKlines`，因此 AI 指标、触发器及固定上下文共同使用的加载器得到相同闭柱、去重、缺口、OHLC、时间对齐和尾部时效政策。

新 PAPER 路径另外具备：

- 每个信号记录完整闭柱输入摘要和 asOf；报价单独记录原始时间，最多 90 秒内消费信号；报价最大年龄 15 秒。
- 预热历史只用于指标，不生成历史交易；入场必须由之后实际观察到的报价触发，加上预先固定的滑点和费用假设。不会拿未来 K 线开盘价填回过去。
- 已消费的重叠历史发生修订时拒绝；缺口、冲突重复、非法柱和过期尾部停止推进游标。每次最多 4 页回补，超过能力就保留未知。
- 游标、仓位、信号和记账在同一 SQLite 事务提交，数据库故障恢复内存；配置或实现指纹变化拒绝续跑同一实验。
- 旧仓的报价止损独立于 K 线获取；暂停新增风险后仍处理已有仓位退出。仅为本地虚拟仓，不等同生产断网仍有交易所保护单。
- 止损穿价使用更差的开盘/报价，再加不利滑点；OHLC 无法给出触发时刻，同柱入场的柱极值可能含入场前价格，只能保守计损并明确其不确定性。回填观察时间和假设生效时间分别保留，不冒充实时退出。

公共报价试跑最初触发“未来报价”拒绝：Bybit 时钟比本机快约 1 秒。保留 [forward-v1-clock-rejections.json](forward-v1-clock-rejections.json)，没有把失败样本删掉。新增独立服务器时间校准，限制绝对偏差 5 秒及往返时间 2 秒，保留 RTT 上下界；闭柱使用较早时界，报价观察使用较晚时界。报价过期阈值未放宽。修订只影响时钟处理，规则与成本不变，新实现使用独立 v2 账本，旧账本保留。

[paper-scenarios.json](paper-scenarios.json) 是新 PAPER 的 10 类合成场景：正常、急涨、急跌、极端波动、断网、重启、超时、重复响应、缺失、乱序。每组仅一次入场；缺失数据拒绝推进；极端跳价据实计更大损失。API 超时是受控传输异常、重启是重建对象/文件库；真实子进程中断证据来自第 1 步，不宣称树莓派断电已测试。

[legacy-fault-comparison.json](legacy-fault-comparison.json) 重新执行原 QF-S v5 基线与此前修复的同数据、同参数、同成本 10 组对照，包含回撤、交易次数、费用、退出延迟和漏止损。它是原 v5 的工程对照，不与新策略收益混排。第 1 步留下的真实行情 42 笔退出实验仍保留于旧报告，本次未冒充重新跑过。

## 4. 冻结的前向研究实验

[experiment-v1.json](experiment-v1.json)：BTCUSDT，15 分钟闭柱，滚动 240 柱预热，EMA20/60 交叉；ATR 为最近 14 个 TR 的算术均值，止损 1.2 ATR；最多一仓，名义上限虚拟权益 1 倍，风险预算 1%；96 根柱 TTL；日损失 3%、回撤 10% 后停止新增风险并保留旧仓退出。阈值不能保证跳空/故障时损失不会超过它们。风控盯市尚未包含未知资金费。

每边手续费假设 0.055%，滑点假设 0.05%，都不是实际账户费率/成交实证；资金费未知，因此 `net_equity=null`、`complete_net_performance=false`。初始虚拟资金 200 USDT。选择该规则是为了获得一个简单可证伪的实验对象，未做参数搜索，不沿用“旧 v5 盈利所以有优势”的结论；它不是旧 Python/FastAPI 项目，也不替换部署中的影子程序。

程序 `tools/run_verified_paper.py` 仅允许服务器时间、K 线、ticker 三个公开 GET 端点，完全没有凭证和订单 API。默认只运行一次，有界最多 120 次，不安装服务或无限重试。

v2 的 [forward-observation.json](forward-observation.json)、[forward-event-summary.json](forward-event-summary.json) 记录两次各 3 轮真实公开行情运行：6 个报价、1 个启动后新闭合柱及信号，0 笔开仓、0 笔平仓；资金费和完整净值未知。**0 回撤/0 费用只是没有交易，不能算策略成功。** 实验并未在后台继续运行。

预登记研究观察窗口为从 v2 注册起的 28 个日历日；届时按实际覆盖度、未知成本和有效独立样本判断是否能评估，不能按“满 28 天”自动通过。若采集不连续、无交易或证据不足，结论就是不足，不挑有利区间补齐。修改规则必须另建实验，保留所有失败臂。本次只完成启动与工程观察，没有等待未来数据或宣布预测优势。

## 复现与测试

最终 Java **57 tests / failures 0 / errors 0**；Python `tools/tests` **38 项**及训练时间 **1 项**通过，合计 **39 项**。覆盖账本金额/未知成本、重复/冲突事件、余额链和转账、行情污染、过期信号、重启、故障回滚、现仓保护及端点白名单。原始输出留在私有目录。空白检查通过；没有新增运行依赖。

```powershell
.\mvnw.cmd test
python -m unittest discover -s tools/tests -p 'test_*.py' -v
python -m unittest discover -s tools -p test_audit_training_timestamps.py -v
python tools/audit_net_ledger.py --snapshot .audit-private/qfs-audit-20261112-0805 --ledger .audit-private/steps234-20261114/exchange-ledger.sqlite --output docs/steps234-20261114
python tools/audit_cashflows.py --capture .audit-private/steps234-20261114/qfs-step234-20261114 --ledger .audit-private/steps234-20261114/exchange-ledger.sqlite --output docs/steps234-20261114/cashflow-reconciliation.json --execution-snapshot .audit-private/qfs-audit-20261112-0805
python tools/audit_verified_scenarios.py --config docs/steps234-20261114/experiment-v1.json --output docs/steps234-20261114/paper-scenarios.json
```

继续有界 PAPER 采集的命令（真实行情仅公开 GET，本地模拟记账）：

```powershell
python tools/run_verified_paper.py --config docs/steps234-20261114/experiment-v1.json --db .audit-private/steps234-20261114/forward-v2.sqlite --report .audit-private/steps234-20261114/next-observation.json --polls 30 --poll-seconds 60
```

旧报告和本次公开结果不会被此命令覆盖。实现或配置变化会拒绝原实验，不应删除旧账本绕过；应记录修订并新建实验。

下一步准入工作仍为：完成退出命令和逐笔成交归属、补齐完整成本/盯市数据、Java 全链路共同 asOf、生产保护与接管验证。之后才可准备受控 Demo 部署。没有用户授权前不执行部署或账户订单。

字段含义按官方核查：[K 线](https://bybit-exchange.github.io/docs/v5/market/kline)、[ticker](https://bybit-exchange.github.io/docs/v5/market/tickers)、[资金流水符号与余额公式](https://bybit-exchange.github.io/docs/v5/account/transaction-log)。
