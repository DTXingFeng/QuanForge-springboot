# QuanForge-springboot 项目审计报告（v2 · 局域网可信环境定级）

> 审计日期：2026-11-15 · 定级前提：**系统完全运行于局域网，所有接入设备可信**——外部攻击者模型不成立。
> 在此前提下，鉴权缺失、SSRF、明文回显等"需要攻击者输入"的发现全部剔除；保留的是**会真实影响交易正确性、资金记账、服务连续性与故障恢复**的问题，以及少数不受局域网边界保护的外部面（Telegram）。
> v1 全量安全报告中的发现仍附于附录，供环境变更时参考。

---

## 一、总体结论

安全不再是问题；**真正的问题是四处并发/状态机缺陷会实际咬到你，其中一处默认配置下必现**，外加本地副本与远端仓库脱钩（领先约 2 个月疑似未推送）与无日志落盘两处工程短板。

| 维度 | 评级 | 一句话结论 |
|---|---|---|
| 交易循环健壮性 | 🔴 严重 | 默认配置第一单即触发全局死锁；另有丢失更新/饿死三处竞态 |
| 资金记账 | 🟠 高危 | closed-pnl 归因污染 + 手续费未入账 + pnl=0 判胜 |
| 运维连续性 | 🟠 高危 | 本地副本无 .git 且领先远端 2 个月（疑似孤本）、无日志落盘、fresh clone 打包缺 UI |
| 测试 | 🟢 良好 | 执行安全类扎实；交易核心路径仍有盲区 |

---

## 二、P0 — 默认配置必现 / 无法回滚

### P0-1 确定性下单失败被当"结果未知" → PENDING 永久卡死 + 全品种封死自动交易（默认配置必现）
- **证据**：AiAdviceTracker.java:171-201,451-461（所有 placeEntry 异常一律保留 PENDING 禁止重下）；DemoOrderExecutor.java:59-76,231-254（对账找不到单抛"保留未知意图"被外层吞掉）；BybitPostClient.java:64-66（`account-writes-enabled=false` 时 postTo 直接抛 IllegalStateException）。
- **机理**：参数校验失败、预算不足最小下单量、`account-writes-enabled=false`——这些都是**发出 HTTP 之前的确定性失败**，交易所根本不存在该 orderLinkId 的委托。但 tracker 把它们与"请求可能已到达交易所的网络超时"同等对待：保留 PENDING → 每分钟对账 `orderDetailByLink` 找不到单 → 抛异常被吞 → PENDING 永不过期。而 93-96 行"存在任一 DEMO 活跃跟踪即禁止新增/反转"使**整个自动交易循环全品种永久停摆**，只能手工改库。
- **触发条件**：默认配置（account-writes 未开）+ 打开 autoOrderEnabled，第一单必现。开了 account-writes 后，预算不足/参数错误同样触发。
- **修复**：把本地确定性异常（IllegalArgumentException / IllegalStateException / account-writes 未启用）与 IOException/超时区分开——前者直接 `expire(t, "下单前置失败")` 释放槽位；仅后者保留对账语义。改动集中在 placeEntry 的 catch 分类，工作量小、收益最大。

### P0-2 远端仓库存在且卫生良好，但本地副本领先远端约 2 个月且疑似未推送——本地是唯一副本（2026-11-15 复核修正）
- **核实结论**：远端公库 [github.com/DTXingFeng/QuanForge-springboot](https://github.com/DTXingFeng/QuanForge-springboot) 确实存在（v1"无仓库"结论有误）。公开库卫生已逐项验证：① 顶层无 `application-local.yaml`、无 `data/`、无 `.audit-private/`（gitignore 远端生效 ✓）；② `deploy/*.service` 仅含策略参数，无 token/secret；③ `tools/` 无硬编码 bot_token/api_secret/APP_CRYPTO_KEY，且有专门 commit 做过"真实 token 改环境变量注入"清理；④ README 已明示"无鉴权仅限本机、示例密钥勿存真实凭证"——与本项目"局域网可信"定位一致。
- **真正的问题**：
  1. **本地工作树（E:\project\QuanForge-springboot）缺失 `.git` 元数据**——是仓库的裸副本，无法 commit/diff/回滚；
  2. **远端 main 最后可见提交**：src @ Aug 24（v4.8.5 孤儿守卫修复）、tools @ Sep 19；**本地已是 v5.1-paperlab-20261115**（SystemVersion.java:42，含 paper/ 模块、DemoOrderExecutor、AiAdviceTracker 大改、12 个测试文件、`.audit-private` 中 11/12-11/14 的产物）——**v4.8.5 → v5.1 近两个月的全部工作在远端 main 不可见**（除非已推送至其他分支）。当前这份本地副本若是孤本，一次磁盘故障即丢两个月交易系统迭代。
- **修复**：恢复本地 .git（`git clone` 远端后合并本地树，或 `git init` + 关联远端 force-push 前先 diff）；确认 v5.x 工作已推送；把"推送"纳入日常（deploy 里已有 systemd 体系，说明这台机器是生产树莓派之外的另一工作副本，两处同步策略要明确）。

---

## 三、P1 — 高危（并发竞态与连续性）

| # | 发现 | 证据 | 要点与修复 |
|---|---|---|---|
| P1-1 | **review() 与 settle() 无锁并行写同一跟踪行 → 已结算行被"复活"** | PositionManagerService.java:74-76,193-207,239-248 × AiAdviceTracker.java:412-414,580-598；AiAdviceTrack.java:34-36 无 @Version | review 加载列表后做分钟级 LLM 判断，期间 settle 可能已结算该行为 WIN/LOSS；随后 review 的 `save(t)` 把过期 status=TRACKING 整行写回 → 重复对账、重复 TG 推送、SETTLED_ESTIMATE 重复入账；反向则 DB 与交易所 TP/SL 不一致。**修复**：AiAdviceTrack 加 @Version 乐观锁，或收敛为单一写者（review 向 tracker 投递指令） |
| P1-2 | **review() 长事务包住 LLM 调用 → 连接饥饿 + BUSY_SNAPSHOT 回滚分歧** | PositionManagerService.java:75,81-91,297-307；application.yaml:26-29（Hikari=2） | 事务覆盖"查列表→每品种 LLM(读超时120s)→改单→save"，独占 1/2 连接分钟级，settle/TG/Web 争抢剩余 1 条；WAL 下事务中途升级写触发 `SQLITE_BUSY_SNAPSHOT`（busy_timeout 无效，AiAdviceTracker.java:203-205 已有实战记录）→ 整个回滚但**交易所 TP/SL 已改**，DB 留旧值。**修复**：去掉 @Transactional，逐动作短事务（模仿 tracker 的 NOT_SUPPORTED+逐条 save），HTTP 一律移出事务 |
| P1-3 | **调度池 4 线程 vs 6 类长任务 → settle 饿死，DEMO 成交后 TP/SL 数分钟无人补设** | application.yaml:14-17；AiAnalysisService.java:80-107；TelegramBotService.java:88-101；AiAdviceTracker.java:412,529-577 | tick/review 单品种 LLM 可达 10 分钟级，TG getUpdates 服务端挂起 25s+fixedDelay 2s 近乎常驻；三者占满后 settle（成交确认与补 TP/SL 的心跳）被排队延迟，只能靠 OrphanGuard 5 分钟一轮 0.3% 缓冲止损兜底——正是其注释里"100x 杠杆裸奔"事故的早期窗口。**修复**：LLM 判研移 @Async 独立池+单飞标志；TG 轮询拆独立单线程；settle 与 LLM 类任务线程隔离 |
| P1-4 | **日志无落盘策略 → 事故取证无保障** | application.yaml 无 logging 段、无 logback-spring.xml | 曾因文件日志刷出 858MB，现行对策是"干脆不配"仅控制台输出——下次再出 v4.8.1 式白亏事故时，重启即证据全灭。**修复**：logback-spring.xml 滚动策略（按天+按大小，保留 14 天，ERROR 独立文件），与 858MB 教训兼容 |
| P1-5 | **前端构建链不闭合 → fresh clone 打出无 UI 的 jar** | pom.xml:99-112 + .gitignore:37-38 | pom 把 `frontend/dist` 映射为 static，但 dist 被 gitignore 且无 frontend-maven-plugin——新环境（或将来 git init 后的克隆）直接 `mvn package` 得到**没有 UI 的 jar**（Maven 对缺失资源目录静默跳过不报错）；且树内 src/main/resources/static/ 残留过期产物（index-BwKaYT6t.js ≠ dist 的 index-D2w7nU9d.js）易误导排查。**修复**：加 frontend-maven-plugin 绑定 generate-resources 阶段；删除树内 static 残留 |

---

## 四、P2 — 中危（记账口径、竞态细节、工程欠账）

### 资金记账（直接影响胜率统计与 AI 反馈回路）
1. **closed-pnl 归因污染**（DemoOrderExecutor.java:305-331、AiAdviceTracker.java:580-598）：按 symbol+时间窗（入场前 60s 起）聚合**该品种全部**平仓记录（limit 50）——你在同 demo 账户手工交易同品种、或上一笔的迟到平仓，盈亏被合并进本单。修复：按 orderLinkId/orderId 归属过滤，或 createdTime+qty 精确匹配。
2. **手续费/资金费未入账**（DemoOrderExecutor.java:300-304 注释自认）：openFee/closeFee/fundingFee 缺失，`pnl>=0` 即判 WIN——手续费后的小亏单被记成胜，小额盈利单可能反向判级。AI 的建议质量反馈（resultPct）被系统性污染。修复：净口径 = pnl − openFee − closeFee − funding。
3. **TP/SL 取整方向**（DemoOrderExecutor.java:376-397）：qty 用 FLOOR 正确，但 roundToTick HALF_UP 可向不利方向多让半个 tick（BUY 的 SL 向下、TP 向上）。修复：按"不利方向不放宽"原则取整；结算区分"未知"与 0（demoPct 的 qty null 时现在记 0%）。

### 竞态与资源
4. **OrphanPositionGuard 与 tracker/PM 竞态**（OrphanPositionGuard.java:34-80 × AiAdviceTracker.java:529-577 × PositionManagerService.java:193-248）：巡检快照后逐个设止损，与 enterDemo 重试、applyClose 平仓交错——已保护仓位被"保护性市价平仓"白亏（复现 v4.8.1 ~0.5% 事故）；正被平时设 SL 收 retCode=10001 触发误告警。修复：巡检对有 TRACKING/PENDING 意图的 symbol 跳过或降级只告警。
5. **限频时熔断/波动门槛 fail-open**（AiAdviceTracker.java:303-306,336-338；BybitGetClient.java:116-129 不查 retCode）：行情最关键时段（限频高发）保护恰好静默失效；`getPublic` 把代理 502 HTML 原样上抛 JSONException，掩盖真实原因。修复：getPublicRaw 统一校验 retCode/HTTP + 10006/429 指数退避；门槛失效时显式标注"未评估"而非默认放行。
6. **OkHttp 代理客户端缓存无淘汰**（BybitBaseClient.java:35,59-73、ProxiedHttpClients.java:40,68-82）：代理配置每次变更产生新 key，旧 client（独立 ConnectionPool/Dispatcher 线程/socket）永不回收。你若频繁换代理端口，长期运行内存/FD 缓慢泄漏。修复：共享 ConnectionPool/Dispatcher 仅差异化 proxy，或键变化时 `evictAll()` 旧 client。
7. **DEMO 写库无 BUSY 重试**（AiAdviceTracker.java:177-200）：PAPER 分支 3 次重试未覆盖 DEMO 分支 saveAndFlush；一次 BUSY 异常即中断当前意图处理，靠下一轮心跳修复。修复：统一套用重试。
8. **凭证名静默回退第一条**（BybitService.java:235-243）：**这不是安全问题，是交易正确性问题**——多凭证时名字拼错/删除后，create-order/trading-stop 等走 `post()` 回退的仍是第一条凭证 = **可能对错误账户下单**；TG /positions 与 AI get_wallet 读到别的账户数据，LLM 据此误判。postDemo 已精确解析，post() 应同样删除回退、未知名 404。

### 工程欠账
9. **ddl-auto: update 无迁移工具**（application.yaml:37）：SQLite 上 schema 漂移不可审计；改 validate + Flyway，或至少生产 profile 锁 validate。
10. **无 actuator**：长跑服务无存活探针；加 starter 仅暴露 health,info 即可。
11. **Boot 4.1.0 首发版**（pom.xml:8）：GA 约 5 个月、4.1 线最早期补丁周期；org.json 20260522 上游响应解析有已修 CVE-2026-59171（超大数 DoS——上游是 Bybit/AI 返回的 JSON，属不受控输入，与局域网无关，建议顺手升 20260814）。
12. **测试盲区**：BybitController（真实下单 REST 面）、BybitBaseClient HMAC 签名拼装（签名错=资金风险，应有固定向量测试）、PositionManagerService、AesEncryptor 异常路径（篡改密文/错误密钥/非 32 字节 key）均无直接测试。

---

## 五、P3 — 低危 / 观察项（保留 v1 结论，摘要）

1. **TG 绑定机制核实结论（2026-11-15 复查）**：绑定后为**严格白名单，实现正确**——TelegramBotService.java:132-135 对非绑定会话精确比对 chatId 并忽略+告警日志；解绑只能经局域网 Web UI（`PUT /api/tg/config`），聊天侧无法覆盖既有绑定；指令集本身无实盘交易命令。残余风险仅一个**很窄的窗口**：TelegramBotService.java:126-131，`chatId` 为空时（保存 token 后、主人首次 /start 前）第一个发 /start 的会话自动成为绑定者——但 bot 用户名不公开列示，外人需先知道你的 bot @username，实际可利用性低；且误绑后经 Web UI 清空 chatId 即可重绑。此外 `/analyze` 会走 manual 路径（AiAnalysisService.java:195 manual=true 跳过 NONE 过滤，:210 有建议三元组即 track），autoOrderEnabled 开启时可在 DEMO 环境触发自动单——实盘无虞。**定级：低（设计取舍，个人 bot 常见做法），配对码可作为可选增强而非必须**。
2. volGateCheck 无 finite 校验 → atrPct NaN 静默放行；momentum 遇 close=0 产生 Infinity 拼进 LLM prompt（AiAdviceTracker.java:286-299、PositionManagerService.java:341-358）。
3. 异常吞噬清单：AiToolRegistry.klineArrays 吞一切返回 null（限频/断连不可见）；num() 失败静默返 0 喂 LLM；TG send 吞发送失败（孤儿仓告警丢失无补偿）；多处 catch 仅 e.getMessage() 无堆栈。
4. ExecutionJournal 幂等去重会把内容相同的两次真实事件折叠为一条；崩溃窗口内观察永久丢失（注释已自认）。
5. CredentialHealthRegistry last-write-wins：一次瞬时 10006/5xx 覆盖刚验证的 VALID。
6. AiConfigService/TelegramBotService 单例"查→建→存"首次并发双 INSERT 竞态（仅启动瞬间）。
7. TelegramBotService.runAsync 无并发上限：/analyze 刷屏并发拉起多个 agentic 循环争抢 tracker 锁。
8. 杂项：HELP.md 样板残留；SystemVersion javadoc 止于 v4.8.5 与实际 v5.1 脱节；format_sql 死配置；paper 模式 .proxy-runtime.json 明文落盘（POSIX 权限缓解，Windows 无等效）。

---

## 六、值得肯定的亮点（维持 v1 结论）

- 崩溃恢复不重复下单：orderLinkId 先持久化后发单 + 交易所幂等 + demoSlot 唯一约束。
- 账户写门禁默认 false；DEMO 自动交易钉死 demo 域名（postDemo/postTo 分离），不受 UI 模式切换影响。
- AES-GCM 实现规范（随机 12B IV 前置、128-bit tag）；零密钥日志；show-sql false / open-in-view false。
- 测试纪律好：:memory: 库+关调度，无 Thread.sleep；意图日志/崩溃恢复/孤儿仓防线有专项测试（执行安全 20 例+纸面结算 12 例）。

---

## 七、修复路线图（局域网定级后）

1. **立刻**：P0-1 PENDING 死锁（一处 catch 分类即可解，默认配置下它是"功能根本跑不起来"级别）→ P0-2 恢复本地 .git 并把 v5.x 工作推送远端（远端仓库已确认存在，只是本地副本脱钩）。
2. **本周**：P1-1 @Version → P1-2 拆事务 → P1-3 线程池隔离 → P1-4 logback 落盘 → P1-5 frontend-maven-plugin。
3. **两周内**：P2-1/2/3 记账口径（手续费+归因+取整，AI 反馈回路的数据质量）→ P2-4/5/6/7/8 竞态与退避 → P2-9/10/11 工程项。
4. **持续**：P2-12 补签名向量/控制器测试；P3 随迭代清理（TG 绑定已核实为正确白名单，仅窗口期有理论风险，无需专门处理）。

---

## 附录：v1 安全发现的处置说明（威胁模型=可信局域网）

| v1 编号 | 发现 | 处置 |
|---|---|---|
| P0-1/P0-2/P0-3(v1) | 零鉴权、明文密钥回显、默认密钥回退、密钥与 DB 同树 | **降级为知情项**：仅当出现"端口映射到公网 / 目录被拷出机器 / 交给他人运行"任一情形时升级回 P0。建议至少保留 `server.address: 127.0.0.1`（一行配置，零成本保险） |
| P1-1/2/3(v1) | endpoint SSRF、代理改指向、AI baseUrl 外带 | 剔除（需要攻击者输入，可信环境无此输入源） |
| P2(v1) | CSRF、参数不编码、CORS | 剔除 |
| P3(v1) | TG 抢绑 | **已复查修正**：绑定后为严格白名单（TelegramBotService.java:132-135），实现正确；仅未绑定窗口期存在理论抢绑面，且 bot 用户名不公开、误绑可经 Web UI 重置——降级为低危观察项，见 P3-1；org.json CVE 保留（上游输入触发） |

*报告 v2 由 v1 三路并行审计结果按新威胁模型重排而成；全部结论附文件:行号证据。*
