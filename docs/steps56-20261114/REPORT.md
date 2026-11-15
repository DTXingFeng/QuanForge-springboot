# 第 5、6 步：候选发布、Demo 准入与 AI 增益验证

日期：2026-11-14，Asia/Hong_Kong。结论：**候选包及本地观察启动验证已完成；交易所 Demo 准入未通过；策略与 AI 优势证据不足。** 没有部署、重启树莓派、修改凭证、调整账户资金或发单，没有新调用付费 AI。

## 第 5 步的实际交付

[candidate-package.json](candidate-package.json) 指向本地候选 ZIP、JAR 和 manifest 校验值。候选版本 `v4.8.7-audit-20261114`，JAR SHA256：

```text
7b450347dd31051f68f06839e92470e357128e95b0c3de1da7eb971cfa6efe02
```

包内包含 JAR、当前 React 构建资源、一次性 schema 迁移和 [RUNBOOK.md](RUNBOOK.md)，附文件哈希、源码指纹和测试结果；不含交易历史、凭证、私有配置或旧部署 JAR。打包程序 `tools/package_candidate.py` 不具备部署能力，拒绝覆盖旧候选包，并校验测试时效、默认写开关、私有配置排除及前端资源一致性。

### 新确认并修复的构建与发布问题

1. **旧本地候选 JAR 确实包含 `BOOT-INF/classes/application-local.yaml`。** Git ignore 没有阻止 Maven 打包。未打印该文件内容，未将旧 JAR 公开分发。本次在资源规则中排除本地配置和 `.env`，清理后重建，并直接检查新 JAR 内容确认排除。[artifact-verification.json](artifact-verification.json) 保存结果。
2. 原账户 POST 客户端没有独立默认关闭的写入开关。[write-gate-before.txt](write-gate-before.txt) 是实际失败测试。现在 `app.execution.account-writes-enabled` 默认 false，通用 POST 和 Demo POST 都在创建签名请求前拒绝；已有 Demo 域名固定测试在显式开启且 HTTP 被拦截的隔离条件下继续验证。没有访问真实订单接口。
3. 原 `@EnableScheduling` 无法通过候选观察配置关闭。改为条件配置；观察启动设置 `app.scheduling.enabled=false` 时不存在定时任务处理器，且所有原定时任务保持默认启用行为，方便将来经过准入后恢复。账户写操作仍默认关闭，两者是独立控制。
4. 前端由已验证的 `frontend/dist` 直接进入 JAR 的 static 目录，旧资源目录不再混入；打包时逐文件比对嵌入资源和构建资源。

**关闭写入也会阻止撤单、平仓和保护单更新；关闭调度也会停止持仓管理。** 因此该候选观察模式只能在仓位已独立核对为空或已有可靠外部接管时使用，不是带仓位的紧急保护工具。

### 本地真实 JAR 启动验证

用候选包中同指纹的 JAR、单独新目录及新 SQLite 启动，绑定 `127.0.0.1:40876`，显式关闭调度和账户写操作。结果见 [observer-smoke.json](observer-smoke.json)：

- HTTP 页面返回 200，内容与当前 React 构建完全一致。
- `/api/bybit/mode` 返回 DEMO；该结果不等同交易所连接认证。
- 测试库凭证行数 0；没有使用运行库、实际密钥或已存在交易历史。
- 测试后核对进程命令行并停止本地观察进程，没有留下后台服务。

迁移在真实备份的副本执行：[schema-copy.json](schema-copy.json) 显示 823→823 条，integrity_check=ok，新增观察表可用。没有在生产库执行。旧部署 JAR 已只读保存于私有目录，指纹与树莓派一致：`980b07de865cbb6714f64dc9cb90847c2cc8670b6dcd146ee9f4258a4dbf697d`。回退包不公开旧 JAR，因为它可能包含原私有配置；回退不允许用旧数据库覆盖维护后新增交易。

### 为什么没有进入交易所 Demo 发单

[runtime-observation.json](runtime-observation.json) 是本轮新只读观察：树莓派主服务仍为旧指纹；Java 配置的单一 Demo 账户在完整分页下仓位 0、活动委托 0；凭证名称与代码默认名称不匹配；影子账户未独立验证。

[demo-readiness.json](demo-readiness.json) 给出 `ready_for_controlled_demo=false`。实际阻碍包括：

- 显式账户映射尚未完成，影子账户不能由 Java 空仓代证。
- 持久化退出命令、精确成交/费用归属仍未闭环。
- Java AI、多工具、模型 sidecar 和执行端尚未证明共享相同行情时点。
- 交易所保护单及故障接管没有真实接口验收。
- 该具体候选尚未进行使用者部署审阅；技术阻碍即使获得部署许可也仍需解决。

`tools/demo_readiness.py` 对缺失、未知、字符串 true、过期观察和候选哈希不一致均拒绝准入。本地测试通过不会自动填平这些缺口。这是第 5 步准入失败的明确结果，不能写成“受控 Demo 已通过”。观察有 5 分钟时效，未来部署必须重新取证。

## 第 6 步的验证方案与当前结论

[ai-trial-protocol.json](ai-trial-protocol.json) 锁定模型别名、提示词模板源码指纹、规则/实现指纹、评估器指纹、观察窗口与成本口径。运行配置读到的别名为 `gemini-3.8-flash-high`，只是服务商配置名，**没有证明其底层模型身份或版本**，不能当作官方型号认证。

为使归因可解释，本轮只准备 AI 对固定规则入场的 TAKE/SKIP 对照：TAKE 沿用完全相同的方向、仓位、退出和成本；SKIP 不开该虚拟交易。AI 不另选方向、不改退出、不增加杠杆。该试验只检验“AI 过滤现有规则信号是否增益”，不代表所有 AI 用法。

程序 `tools/ai_trial.py`：

- 仅接收注册后的闭柱输入，保存 asOf、快照、实际接收时间；拒绝倒填历史、未闭柱及未来输入。
- 先封存首个预测，再接受结果；结果先到、预测迟到、版本不符或非法决策都保留为失败，按原规则回退，仍计已知 API 成本。不能挑选多个回答中最好的一次。
- 每个预定 15 分钟时点都需要记录，包括 HOLD、未成交和失败。漏帧、未结算、未知费用/资金费/API 成本均阻止完整结论，不只统计获胜/已知子集。
- 按相同交易机会配对，扣除手续费、资金费、滑点及全部已知 API 成本。`gross` 定义为参考价格下的毛现金收益，滑点另扣；不能把已经含滑点的实际价差再扣一次。
- 预设 56 日窗口、至少 100 个已闭合机会和 8 个完整周块，固定种子做周块重采样。95% 区间下界大于 0、AI 总净额为正以及所有质量门槛同时满足，才允许报告此试验的条件性增益。数量门槛不是统计功效保证，周块也不保证市场完全独立或未来盈利。
- 配置与评估实现变化拒绝沿用原实验。旧 v1 空注册保留；在封存评估器指纹后使用独立 v2 空试验，未删除任何交易或预测。

本地时间收执和哈希用于发现实现变化及常见事后补写，并非第三方不可篡改证明；真实研究还需与采集日志、输入来源和版本交叉核对。

所有检验使用模拟输入测试，没有为“证明 AI 有效”调用新模型。正例控制明确为人工构造的数据，用于检查程序能识别已知差异；它不属于 AI 或市场业绩。始终 TAKE 的负例、事后预测、未知成本、零预算超支及模型身份不明均不能获得通过结论。

### 当前实际评估

[ai-evaluation.json](ai-evaluation.json)：**未来有效帧 0、闭合机会 0、完整周块 0，`ai_increment_proven=false`**。费用预算和新付费调用次数上限均为 0，未调用外部模型。模型身份未确认，无法进行有意义的增益认证。

原 PAPER 实验仍只有极短观察和 0 笔入场，不能证明规则策略存在净优势；也不能据此证明其必然无优势。旧策略的亏损与旧审计中的工程缺陷保留为反证，不把历史 AI 告警重新包装成提前封存的未来预测。

此评估器尚未接入持续行情/模型采集任务；本轮只完成冻结协议、可运行评估器和反作弊/负例验证。不能将空试验或已通过的程序测试描述为实际 AI 对照已完成。当前没有后台采集、自动模型调用或无人值守交易。

## 验证结果和复现

最终 Java **59 项**，Python `tools/tests` **47 项**＋训练时间 **1 项**，合计 **48 项**，全部通过。React 构建通过，原有大 chunk 警告保留。候选 JAR 已实际在本地隔离启动，schema 副本检查通过。真实订单、生产迁移与服务回退没有执行，不算测试通过。

```powershell
cd frontend
npm run build
cd ..
.\mvnw.cmd clean package
python -m unittest discover -s tools/tests -p 'test_*.py' -v
python -m unittest discover -s tools -p test_audit_training_timestamps.py -v
python tools/demo_readiness.py --evidence docs/steps56-20261114/readiness-evidence.json --out .audit-private/steps56-20261114/readiness-rerun.json
python tools/ai_trial.py --protocol docs/steps56-20261114/ai-trial-protocol.json --db .audit-private/steps56-20261114/ai-trial-v2.sqlite --report .audit-private/steps56-20261114/ai-rerun.json
```

Demo 准入命令在当前证据下应返回非零；AI 评估会保留“不足”结论，不能当成功信号。重建 JAR 会改变其哈希，需要重新生成候选包并重新审阅，不能套用旧 manifest。所有累计源码改动仍可通过 Git diff 查看，未提交、推送或部署。

官方规则核查：[Demo 独立账户与域名/接口范围](https://bybit-exchange.github.io/docs/v5/demo)、[Maven 资源排除规则](https://maven.apache.org/plugins/maven-resources-plugin/examples/include-exclude.html)。实际构建与账户状态以本报告所附本地证据为准。
