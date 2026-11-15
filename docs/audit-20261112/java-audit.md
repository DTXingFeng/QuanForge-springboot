# QF-S Java 交易链路审计（2026-11-12）

本报告只研究本仓库 Spring Boot QF-S。树莓派同机旧版 FastAPI 服务不属于本报告证据。生产只读快照目录由主审计报告记录；本文的源代码引用为仓库相对路径，行号以交付 diff 为准。

## 证据边界与真实链路

快照中 Java 配置 `auto_order_enabled=0, enabled=1, auto_margin_pct=5, leverage=100`。因此当前 AI 仍能生成 PAPER 评估，不能把当下所有建议当成 DEMO 委托。历史数据库确有 DEMO 记录。

1. `AiAnalysisService.tick()/scanSymbol()` REST 拉行情，计算本地触发器；手动分析/桥接触发另有入口，不以定时器频率等价替代实际事件时序。
2. `AiAgentService.judge()` 最多 6 轮（urgent 3 轮）调用只读工具，包括模型 sidecar；不支持 tools 才走固定上下文降级。各工具各自请求，原代码没有统一 immutable 行情快照。
3. `AiAnalysisService.adviceTriple()` 检查 BUY/SELL 几何关系；告警入库后调用 `AiAdviceTracker.track()`。提示词中的“必须查持仓/模型/规格”不是程序强制执行的风控。
4. `track()` 对同 symbol 的现存 PENDING/TRACKING 做取代/反转，做逆势、连败、波动门槛和 majors 止损距离钳制；门槛抓取失败可放行。没有账户级仓位预留或组合风险预算。
5. 关闭自动下单时只建 PAPER 跟踪。开启时调用 `DemoOrderExecutor.placeEntry()`，按 equity × margin% × leverage 算数量；距现价 0.15% 内用 Market，否则 Limit。不能将所有历史交易当作“回调限价”执行。
6. `AiAdviceTracker.settle()` 每分钟巡检。DEMO 以交易所订单/仓位/closed-pnl 为事实；PAPER 则使用独立的 1m OHLC 模拟。`KlineHistoryService` 的 SQLite 历史库并不是 Java 所有实时决策的唯一路径。
7. `PositionManagerService.review()` 每 5 分钟经 LLM 作 CLOSE/MOVE_SL/MOVE_TP/REBASE；majors REBASE 明确允许放宽止损，故“系统从不放宽风险”并不成立。管理状态与 enteredAt/rebasedAt/qty/orderId 在数据库中，但 lastAlertAt/扫描冷却在内存。
8. `OrphanPositionGuard.sweep()` 每 5 分钟补缺失保护；不是实时撮合保护，不能替代随单 SL。
9. `closedPnlSince()` 按 symbol/时间窗聚合最多 50 条；`stats()` 基于记录的 result_pct。它们不是逐 execution、费用、资金费完整核对账本。

已对快照中的 `AiAdviceTracker.class`、`DemoOrderExecutor.class` 用 `javap -p -c` 独立核查：部署字节码的 TTL 分支确有 `getNote != null -> skip`；原入场 JSON 无 TP/SL，调用随全局模式变化的 `BybitService.post()`。取证输出在私有 `.debug/deployed-*-bytecode.txt`；原始部署 class 哈希在快照 `deployed-class-hashes.json`。这些确认不依赖旧报告或代码注释。

## 已复现与已修复

最初 6 个测试在原业务代码运行：`Tests run: 6, Failures: 6, Errors: 0`，见 [java-baseline.txt](java-baseline.txt)。首次尝试曾因 JSONAssert 带入 Android JSON 而出现 `JSONArray.isEmpty NoSuchMethodError`；已在测试依赖中排除该 fork，再跑得到上述真正的 6 个业务失败。生产依赖没有增加。

| 问题 / 修复位置 | 同一输入下原行为 | 修复后行为与测试 |
| --- | --- | --- |
| PAPER 限价入场方向反了；`AiAdviceTracker:561` | BUY 100 遇 high105/low101 仍成交；SELL100 遇 high99/low95 仍成交 | BUY 检查 low<=entry，SELL 检查 high>=entry；两种不触价场景均保持 PENDING |
| 入场无交易所保护；`DemoOrderExecutor:104` | 原下单体没有 stopLoss/takeProfit；完全成交后下一次分钟心跳才挂，部分成交可等 120 分钟 TTL | 随单提交 Full、Market SL/TP、LastPrice 触发；被拒时不尝试去掉保护重下。仅验证协议请求，未向交易所发测试订单 |
| 任意 note 禁用 TTL；`AiAdviceTracker:453` | 已持仓3小时、有管理备注的 alt 不发送平仓 | 同一持仓发送 reduce-only 平仓，不因备注跳过；超时异常保持 TRACKING，后续心跳可重试 |
| 撤单 ACK 当作已撤；`AiAdviceTracker:425` | New/cum0，撤单 ACK 后直接 EXPIRED，后续成交可能失管 | 撤后重新查终态；New仍PENDING，竞态Filled转TRACKING并保护 |
| 反向平仓失败/仅 ACK 也去掉旧跟踪；`:319` | timeout后旧行EXPIRED，新方向可下单 | 异常或尚有旧仓均保留TRACKING并阻止反方向新委托；需仓位归零与盈亏事实再结束 |
| DEMO执行跟随全局REAL；clients + BybitService | 程序名称是Demo但签名GET/POST使用全局模式地址 | Demo专用签名GET/POST直接固定 `api-demo.bybit.com`，测试在全局REAL下拦截OkHttp请求验证域名，不打开socket |
| 默认凭证不存在时取第一条 | 可能误选其他账户 | Demo专用路径只匹配精确凭证，找不到直接失败 |
| 孤儿仅有TP也跳过；`OrphanPositionGuard:50` | TP110/SL0 的持仓完全不补SL | 缺SL即补，不改已有TP |
| minQty导致预算越界；`DemoOrderExecutor:74` | 不足最小量时直接向上抬量，扩大预算 | 放弃下单；不会扩大仓位 |
| TP/SL入参顺序潜伏错位；`AiAdviceTracker:154` | caller传SL,TP，callee参数是TP,SL，原先参数未用使错误隐藏 | 修正顺序，并在executor入口校验有限值、方向价位几何及预算；非法/Infinity值在账户请求之前拒绝 |

订单 link 从毫秒时间改为 35 字符 UUID，消除同毫秒碰撞；这**不等于**已实现跨进程 durable idempotency，不能据此宣称 API 超时后不会重复下单。

随单保护协议依据：[Bybit Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order) 支持随单设置 TP/SL；[Trading Stop](https://bybit-exchange.github.io/docs/v5/position/trading-stop) 说明 Full 模式使用市价退出及内部条件单。交易所实际接受、触发与成交质量仍须未来受控 DEMO 验证。本次未触发任何交易测试、未切REAL、未部署生产。

## 测试说明

复现/回归命令：

```powershell
.\mvnw.cmd '-Dtest=ExecutionSafetyTests,DemoEnvironmentTests' test
```

`ExecutionSafetyTests` 不启动 Spring，不载入数据库/凭证/调度，mock Bybit；`DemoEnvironmentTests` 用 OkHttp interceptor 在请求发出前返回假响应，不打开 socket。最终13+3=16项通过；追加的 `PaperSettlementAuditTests` 12项亦通过，合计本子任务28项均为0失败/0错误。全项目结果以主审计统一重跑记录为准。

后加场景包括重复 Filled 响应、API 平仓 timeout 后重试/确认、取消与成交竞态、重新创建 tracker 恢复持久记录、非法模型价位与预算不足。重建对象测试只证明恢复逻辑，不冒充断电、OS进程重启或SQLite崩溃恢复实测。

这些工程对照不改策略参数，不产生可宣称的收益率/回撤改善。相同输入的异常成交数量由2降0；超时仓位管理不再消失；TTL场景由不发平仓变为发一次并等待确认；SL从轮询后补变为入场请求即携带。收益、滑点、资金费、真实退出延迟无相应订单实验，不能填写虚构改善数字。

## 仍未解决，且影响自动DEMO准入的缺口

1. **P1：entry POST timeout仍回退PAPER**（`AiAdviceTracker:162`）。交易所可能已接受，但客户端没有orderId；缺少先落库的intent、稳定linkId与按linkId重查、跨进程去重状态机。新入场已带保护减轻裸仓后果，但归属/重复/统计错误仍在。当前测试没有证明超时开仓幂等，不能恢复无人值守自动下单。
2. **P1：同symbol并发 check-then-act**。`track()`先查active再下单再存库，四线程调度/手动请求可并发；没有有效跨事务符号锁、唯一active约束或交易意图锁。`@Transactional`不为外部HTTP提供幂等，也不保证两个读后写互斥。不能用“Map是ConcurrentHashMap”替代验证。
3. **P1：共享账户总风险不受控**。每个symbol都按同一totalEquity × marginPct × leverage独立计算，不减未成交占款、不预留在途委托、不核净组合损失上限；例3品种各5%×100x即15倍权益名义敞口。`minQty`修复只管单笔下限，不能解决组合预算；没有日损硬熔断/最大仓数的实际执行链。`get_instrument/get_positions`提示词不等于硬门禁。
4. **P1：closed-pnl归属不精确**（`DemoOrderExecutor:281`）。按symbol时间窗、向前60秒（调用方又减60秒）容易卷入上一笔；limit50无cursor分页；qty未和本跟踪数量严格匹配；partially filled/人工并仓更复杂。不得把当前`result_pct`当作逐笔精确真实亏损。资金费必须另核资金流水，费用应按execution/closed-pnl实际字段核对。
5. **P1：PAPER还不是交易所等价撮合器**。追加修复已处理入场同根SL、未完成条、最新200条覆盖不足、断线后TTL现价漂移（详见下节），但只有1m OHLC时触价先后仍不可识别；同入场柱SL为悲观计损，不奖励该柱TP，并不代表真实逐笔路径。限价成交价格改善、跳空穿SL滑点、流动性、部分成交与成本还未做交易所等价建模。缺口/超预算时保持未知状态并记录告警，不自动伪造成交或盈亏。PAPER结果不能与DEMO收益混用。
6. **P1/P2：AI时间一致性未闭环**。工具多次请求、模型响应与执行器最新价有时间差；无数据asOf/decision expiry硬约束。价位几何检查已存在/加强，不证明时效、实际调用了模型工具或决策依据完整。`PositionManagerService`还以模型自报range/当前配置杠杆和margin估REBASE风险，而非持仓实际qty×止损距/equity；风险上限可偏离真实仓位。
7. **P2：重启恢复并非全丢，也非全保留**。跟踪/价位/orderId/qty/rebasedAt持久化；扫描和告警冷却在内存。外部接受订单与DBcommit之间崩溃、SQLite WAL snapshot写冲突、未flush到commit的错误不受保存重试完整保护。旧版本已在场部分成交裸仓仍依赖巡检，不能把新随单保护倒算给旧历史。
8. **P2：收益统计选择口径**（`AiAdviceTracker.stats:639`）。WIN/LOSS平均与胜率排除EXPIRED；快照中DEMO1条有数值的EXPIRED=-1.45%被排除，PAPER15条合计+4.51%同样被排除。方向不都是美化，但损益统计不完整。其余EXPIRED的未知收益不能擅自补0。表中价变百分比之和不是资金收益率。
9. **P2：5分钟孤儿巡检并非实时保证**。现在漏SL会补，但调用失败、API不可达、hedge mode、positions分页和人工/多策略所有权尚未闭环；当前代码按one-way positionIdx0工作。未建立账户状态一致性协议前，不可声称所有仓位总有人管理。

## 交易记录中可独立核实的关联，不能当因果份额

Java表共有DEMO431（WIN167/LOSS240/EXPIRED24）与PAPER358（WIN127/LOSS180/EXPIRED51）；应与交易所execution/closed-pnl进一步join，不能把表计数等于真实开平次数。记录#191 ACEUSDT为EXPIRED、entered到settled1836.49分钟且result_pct=NULL；#1 BTCUSDT LOSS持352.22分钟且有备注。备注可能在结算时被覆盖，超TTL记录本身不能证明全部延迟由note bug造成。需要时间序列日志/交易所状态，主报告负责合并。

源码缺陷、mock复现能证明错误执行机制，不能直接给出“系统bug占总亏损X%”。策略预测优势需独立未参与调参的样本、准确费用、时间无泄漏数据和前瞻实验验证。本次Java修复不提供策略盈利证据。

## Java层结论

已经发现并修正会显著污染模拟结果及持仓管理的工程缺陷，因此不能把原亏损直接判为“纯策略无优势”；也不能反过来称“修工程后策略就有优势”。当前适合隔离离线回放和有人看护的PAPER验证；在entry超时幂等、组合预算、逐单账本、可靠撮合/数据恢复与账户生命周期闭环前，尚未达到无人值守自动DEMO的工程标准。真实资金交易不在本次验证范围。

## 追加：PAPER有界数据回放与退出修复

主审计要求在不更改策略参数、不触碰DEMO路径的范围内进一步修复Java PAPER结算。新增3个测试先在当时未修复实现运行，均失败（3 failures/0 errors），证据 [java-paper-baseline.txt](java-paper-baseline.txt)：

| 同一OHLC序列 | 原行为 | 修复后 |
| --- | --- | --- |
| BUY100入场bar high101/low94，随后反弹high111 | 入场后返回TRACKING，漏掉SL95 | 当bar保守LOSS -5% |
| 当前未完成bar low94，所有已闭合bar low98 | 以未完成bar判LOSS | 保持TRACKING |
| 中断360分钟，较早bar触SL，最新200bar均未触 | 旧SL漏掉，错误EXPIRED 0% | 回放旧bar判LOSS -5% |

修复后的取数从**信号创建之后第一根完整分钟**开始，结束于当前已闭合bar或该记录TTL最后可用收盘；PENDING最长窗口为等待TTL+持仓TTL，TRACKING只到其实际enteredAt+持仓TTL。每页1000、最多4页，倒向翻页但最终按时间升序；相同重复归并，冲突重复/无效OHLC/时间错位/缺失分钟/无进展/页数预算耗尽抛出可记录异常，持仓状态与未知损益保持原状。没有使用未来K线补洞，也没有重写交易历史。

PENDING成交bar仅处理保守SL；其TP可能发生在成交前，因此不计该柱盈利；后续bar在同一次回放中立即结算。已持久化TRACKING的入场bar也作保守SL复核，避免重启后继续漏掉同柱风险。TTL按截止时刻已经闭合的bar收盘结算，不让截止后的SL/TP或恢复时现价倒灌到历史持仓。

12项 `PaperSettlementAuditTests` 覆盖以上3个复现，以及先TP/后成交歧义、信号前bar不参与、缺失分钟保留状态、3页历史恢复、4页预算停止、TTL后行情不参与、重启后的入场bar、乱序与相同重复归并、重复冲突拒绝。与原16项执行测试合跑28项全通过；[java-paper-fixed.txt](java-paper-fixed.txt) 保留运行输出。验证命令：

```powershell
.\mvnw.cmd '-Dtest=PaperSettlementAuditTests,ExecutionSafetyTests,DemoEnvironmentTests' test
```

这组结果来自合成工程场景；-5%是固定entry100/SL95的名义价变，不是账户净收益，不能用来宣称“修复提高收益”。它证明原版漏掉本应计入的损失，修复甚至会让模拟损益更差但更可信。历史回放与完整费用对照由主报告提供。
