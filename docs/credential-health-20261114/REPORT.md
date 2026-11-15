# Bybit 模拟盘密钥检测与到期提示修复

日期：2026-11-14。用户报告密钥可能过期但没有提示，随后明确是 Bybit Demo，并提供剩余天数为 0 的截图；最后确认已在 Bybit 续期。本轮只读取现有凭证的接口状态，未输出密钥、改凭证、调整资金、发单或部署。

## 当前状态与时间线

树莓派最初的只读钱包查询返回 HTTP 200、retCode=0；这只能确认该请求当时鉴权成功，不能证明密钥未到期或能够交易。

补查密钥元数据时，返回 remaining days 0、expiredAt 为 2026-11-15 06:01:20 UTC，即香港时间 2026-11-15 14:01:20。该时间晚于当时检查时刻，因此“剩余 0 天”不能单独作为已经失效的证据。截图、只读接口可用和精确到期时间需要分别解释，不用其中一个替代其它证据。

用户续期后再次只读核对：[current-readonly-check.json](current-readonly-check.json) 记录钱包与密钥信息接口均 retCode=0，剩余 **91 天**，新到期时间为 **2027-02-14 18:26:15（香港时间）**。确认续期已生效，不需要删除或重新创建本地凭证。这些是当次观察，不是永久有效认证。

## 已确认的产品缺陷

1. 凭证页面只有保存/展示，没有统一健康状态、主动检测或到期预警。新增检测接口前的实际失败用例见 [before.txt](before.txt)。
2. `WalletCard.fetchWallet` 在 HTTP 失败、找不到账户或请求异常时返回 null，而且未判断 Bybit HTTP 200 内的 retCode；页面随后把缺失数据按 0 展示。
3. 原 GET 客户端仅返回 body，检测无法保留 HTTP 状态；普通调用的鉴权失败也没有进入统一状态。
4. 仅增加钱包“成功/失败”仍不足够：必须查询到期元数据，区分未过期、即将到期、已过期及仅只读可用。

## 修复内容

- 新增 `CredentialHealthRegistry`、`CredentialValidationService` 及 `/api/credentials/{id}/health`、`POST /api/credentials/{id}/validate?mode=DEMO`。后者是应用的检测动作，实际向 Bybit 只发签名 GET，不发账户 POST。
- 以明确的凭证 id 和固定环境查询 `/v5/user/query-api`；环境不跟随调用中途的全局切换。元数据接口明确不支持时才退回只读钱包验证，并标为“到期时间和交易能力尚未完整确认”。无默认第一条凭证回退。
- 精确 expiredAt 优先；已到期显示红色，未来 7 天内显示即将到期。remainingDays=0 且精确到期时间仍在未来时显示预警，不误判过期。异常或未知到期元数据不显示完整有效认证。
- 元数据中的只读权限、合约权限配置与真正下单能力分开。任何“有效”提示均说明实际交易未验证，不发送测试订单来确认权限。
- 普通签名 GET/POST 的响应也更新健康状态，公开行情请求不会验证密钥。33004/-2015、10003、权限、IP、签名、时间窗口、限流、网络及服务错误分别提示，不全部写成“过期”。
- 缓存按 key/secret 版本摘要和环境隔离，不储存原始密钥。更换 Secret 或环境不会沿用旧绿灯；元数据检测独立计时，频繁钱包成功不会延长旧到期信息的新鲜度。重启后状态为未检测，前端重查。
- 全局页面增加当前凭证状态、最近观察时间、精确到期时间、倒计时及重新检测按钮。页面可见时每 15 秒读缓存，检测信息超过 5 分钟自动做只读复检；人工续期后可立即手动复检。同一把密钥无需改本地记录即可恢复。
- 凭证列表可逐个检测 Demo 密钥，保存/删除后更新状态。上游原始 retMsg 和异常文本不进入新健康响应，防止上游错误回显密钥。
- 钱包错误明确显示“余额暂不可用，未按零余额处理”，不会把鉴权失败画成空余额。切换凭证后丢弃旧异步结果，避免显示上一个账户的状态或余额。

本轮未扩展 AI 密钥检测，按用户确认聚焦 Bybit Demo。

## 验证

- Java **69 项测试全部通过**。覆盖 HTTP 200 中的过期码、HTTP 状态、环境隔离、凭证版本变化、剩余 0 天与未来到期时间、已过期元数据优先、时钟/网络分类、元数据陈旧、只读降级，以及同一密钥续期后的 HTTP 状态恢复。
- React TypeScript/Vite 构建通过；既有大 chunk 警告保留。
- 使用 `webapp-testing` 技能的 Playwright 浏览器测试，全部 API 被拦截为虚构数据。过期警告、即将到期、网络错误、未知到期情况、续期恢复及钱包不显示假零余额均通过；非检测写请求为 0。结果见 [ui-tests.json](ui-tests.json)。
- 界面截图均为虚构数据：[即将到期](ui-expiring.png)、[续期后](ui-renewed.png)、[过期](ui-expired.png)、[钱包错误](ui-wallet-error.png)。未将用户上传的真实 API 密钥截图放入仓库。

```powershell
.\mvnw.cmd test
npm --prefix frontend run build
python C:/Users/xingfeng/.agents/skills/webapp-testing/scripts/with_server.py --server "npm --prefix frontend run dev -- --host 127.0.0.1 --port 4183" --port 4183 -- python tools/test_credential_health_ui.py
git diff --check
```

原始测试日志及修复前累计 diff 位于 `.audit-private/credential-health-20261114/`。本次没有数据库迁移和新运行依赖。

## 部署边界

修复仅在本地工作区，树莓派仍运行此前版本，因此树莓派页面尚不会获得这些提示。此前生成的候选 ZIP 也不包含本次修复；要更新树莓派，需要重新构建并审阅指定产物后再进行获准的部署。本轮没有因为密钥有效而开启自动下单，也没有改变原有账户写开关。

普通业务请求若没有发生、页面也未打开，内存注册表不会主动定时检测；这不是独立后台告警服务。告警时效为页面可见时的轮询/复检周期，不声称交易所每次状态变化都能瞬时发现。

官方字段和错误定义：[密钥信息](https://bybit-exchange.github.io/docs/v5/user/apikey-info)、[错误码](https://bybit-exchange.github.io/docs/v5/error)。
