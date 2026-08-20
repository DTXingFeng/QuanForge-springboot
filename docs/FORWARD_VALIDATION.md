# QuanForge v4.8.x 前向验证 — 状态与交接

> 更新: 2026-08-20 (进化第12轮收尾)。本文档是任何后续会话接手前向验证的唯一入口。

## 一句话状态

ATR≥0.32% 门槛 + 风险平价仓位 + 趋势规则策略已部署到双胞胎模拟盘（3R对照/5R主候选），
数据流修复后于 **2026-08-20 14:20 CST** 正式开始攒前向样本。**判定阈值 n≥30，
预计 ~3 天后可出第一份前向 vs 回测判定。**

## 服务（Pi 192.168.8.240, /mnt/nvme/quanforge）

| systemd 单元 | 内容 | 状态 |
|---|---|---|
| quanforge | Java v4.8-volgate 演示盘(LLM臂) | active |
| quanforge-bridge | 实时触发桥(kline.1) | active |
| quanforge-paper | 3R对照模拟盘 (tp3R-risk1-gate0.32) | active |
| quanforge-paper5 | 5R主候选模拟盘 (tp5R-risk1-gate0.32) | active |
| quanforge-forward-monitor.timer | 每日 09:00/21:00 自动快照 | active |

## 随时可查

- 实时快照: `python3 /mnt/nvme/quanforge/tools/paper_status.py`
- 前向 vs 回测判定: `python3 /mnt/nvme/quanforge/tools/paper_vs_backtest.py`（n≥30 自动给判定）
- 自动沉淀日志: `data/forward_validation.log`（timer 每日两次追加）
- 记账审计: `python3 /mnt/nvme/quanforge/tools/forward_audit.py`
- 风险画像: `python3 /mnt/nvme/quanforge/tools/risk_profile.py`

## 判定决策树（n≥30 时执行）

1. 跑 `paper_vs_backtest.py`：
   - 5R 前向均笔 vs 回测期望(+0.099%) 差 <0.05pp → **符合回测** → 5R 转正为生产主策略
   - 差 >0 → 优于回测 → 转正且考虑 RISK_PCT 上调
   - 差 <0 → 劣于回测 → 查 3R 对照是否同向劣化：
     - 同向 → 策略整体前向失效 → 回滚门槛或重建触发族
     - 仅5R劣 → 降级用3R
2. 3R 对照预期: 回测 WR 25.2% vs 保本 25.0%（贴线），终值 -45% —— 3R 前向若亏损属**预期内对照行为**
3. 5R 转正后: Java 演示盘同步改风险平价仓位（当前固定5%保证金），SNDK 需先在 Bybit 演示盘 UI 签协议

## 关键结论存档（证据链）

- 回测参考: 3R 200→112(边际-0.2pp, 回撤88.2%) / 5R 200→556(边际+2.7pp, 回撤62.9%)
  — 引擎同款记账重建, 偏差<2.3%
- 门槛样本外: 3R/4R/5R 全转正, walk-forward 稳健
- 数据流修复: Bybit kline data 项无 symbol 字段(在 topic) → 曾致模拟盘/bridge 全静默
  (commit 93f88b1)
- 前向首两笔审计: 3R WIN +1.403%(TP满3R) / 5R LOSS -0.519%(SL满1R),
  equity 206.0/197.9 与引擎公式完全一致
- 边界: 参考回测止 8/19 15:02, 前向起 8/20 14:20, 零重叠

## 已知待办

- SNDKUSDT 演示盘下单需用户在 Bybit UI 签协议(110126)——不阻塞模拟盘验证
- 12轮进化轮次已耗尽: 目标以 blocked(时间门槛) 收尾; 用户说"继续"即可重启
