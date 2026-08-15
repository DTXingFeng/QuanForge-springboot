# QuanForge

Bybit 演示盘（Demo Trading）合约交易工作站：Spring Boot 后端 + React 前端，
内置 16 项技术指标图表、多源快讯聚合、Agentic AI 盯盘研判与建议纸面跟踪。

> [!IMPORTANT]
> **免责声明**：本项目仅供学习研究与个人使用，**不构成任何投资建议**。
> 加密货币合约交易（含高杠杆）风险极高，可能损失全部本金；由本软件产生的任何
> 研判、建议或自动行为，后果由使用者自行承担。
>
> **安全提示**：本服务**没有任何鉴权**，仅限本机使用——切勿将 8080 端口暴露到
> 公网或共享网络；REAL（实盘）模式使用真实资金，请谨慎确认。
> API 密钥以 AES-256-GCM 加密落库，主密钥通过环境变量 `APP_CRYPTO_KEY` 或
> `application-local.yaml`（不入库）提供，请勿使用仓库内置的示例密钥存入真实凭证。

## 功能

- **交易**：Bybit V5 Demo/Real 双模式切换（演示盘默认），下单/持仓/委托/钱包，
  100x 内杠杆设置，SL/TP 附挂。
- **图表**：lightweight-charts 多面板，MA/EMA/BOLL/RSI/MACD/KDJ/STOCH/WR/CCI/DMI/ATR/OBV/MFI/VWAP/SAR
  16 项指标可组合开关（配置存 localStorage）。
- **快讯**：华尔街见闻 / Binance / CoinDesk / Cointelegraph 四源聚合，60s 刷新，
  来源与关键词过滤。
- **AI 盯盘（Phase 1 建议层）**：
  - Agentic 工具循环：模型自主调用 9 个只读工具（行情/K线/指标/盘口/资金费率/快讯/历史研判/持仓/钱包）收集数据后输出结构化研判；
  - 策略画像注入：杠杆、出手门槛（覆盖手续费的最低预期波幅）、自定义备注，随每次研判下发；
  - 剥头皮触发器：5m 急涨急跌 / 波动放大（≥1.8×ATR）/ 布林收窄，叠加原有 15m 涨跌幅 / RSI 极值 / 快讯关键词；
  - 建议纸面跟踪：带价位建议自动记录 PENDING→TRACKING→WIN/LOSS/EXPIRED（1m K 线结算，
    同根 K 线双触发保守判损），胜率/均幅统计上墙——不涉及真实下单。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Java 21 · Spring Boot 4.1 · JPA + SQLite(WAL) · OkHttp 4 |
| 前端 | React 19 · Vite 8 · Tailwind CSS 4 · lightweight-charts 5 · zustand |
| 安全 | API Key/Secret AES-GCM 落库加密（`AesEncryptor`） |

## 运行

```powershell
# 后端（8080）
.\mvnw.cmd spring-boot:run "-Dspring-boot.run.jvmArguments=-Dfile.encoding=UTF-8"

# 前端（5173，代理到 8080）
cd frontend; pnpm install; pnpm dev
```

SQLite 数据库自动创建于 `data/quanforge.db`（不入库）。

## 配置（应用内「设置」页）

- **交易凭证**：Bybit API Key/Secret（需开通 Contract Trading 权限），加密存储。
- **代理**：HTTP/SOCKS，Bybit 请求强制跟随；「AI 与快讯也走代理」可关（用国内 AI 直连更快）；localhost 永远直连。
- **AI 服务**：任意 OpenAI 兼容接口（OpenAI / 智谱 / DeepSeek / Groq / Ollama），
  Key 加密存储；模型需支持 function calling 才能走 Agentic 路径（否则自动降级固定上下文）。
- **策略偏好**：惯用杠杆、出手门槛 %、策略备注——注入 AI 提示词。

## 目录

```
src/main/java/xyz/xingfeng/QuanForge/
  client/      Bybit V5 签名客户端（HMAC-SHA256）+ 代理感知 OkHttpClient 工厂
  controller/  REST API（/api/bybit /api/ai /api/news /api/proxy /api/credentials）
  service/     业务核心（AI Agent 循环、工具注册表、盯盘调度、纸面跟踪、指标计算）
  entity/      JPA 实体（凭证/AI配置/告警/建议跟踪/代理）
  crypto/      AES-GCM 加密转换器
frontend/src/
  pages/       交易台 / 快讯+AI / 凭证 / 设置 / 历史 / 总览
  components/  trading/（图表、订单、持仓、快讯流、AI 告警面板） ui/（shadcn 风格基础件）
  lib/         纯函数技术指标库（与后端 IndicatorMath 同口径）
```

## 路线图

- Phase 1 收尾：跟单按钮（AI 建议一键转订单，手动确认）
- Phase 2（数据门槛：≥30 条已结算建议且胜率 ≥55%）：自动交易——风控链
  （DEMO 模式门禁、单笔上限、持仓数上限、冷却、日亏熔断）、开仓即挂 SL/TP 失败市价平仓、
  一键急停、`ai-` 订单前缀。
- MCP Server：把现有工具注册表暴露给外部 AI 客户端。
