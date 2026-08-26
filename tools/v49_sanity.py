#!/usr/bin/env python3
"""v4.9 最后健全性: 保本出口占比 + 与volgate关系(均值不等检验)"""
import sqlite3, collections

con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_final5.db")
rows = con.execute(
    "select settled_at, symbol, action, entry, stop_loss, take_profit, result_pct "
    "from ai_advice_track where status in ('WIN','LOSS') order by settled_at").fetchall()
con.close()
rows = [r for r in rows if r[4] and r[5] and r[4] > 0 and r[5] > 0]
test = [r for r in rows if r[0][:7] >= "2026-06"]
gate = [r for r in test if abs(r[4] - r[3]) / r[3] * 100 <= 0.40]

n = len(gate)
be = sum(1 for r in gate if abs(r[6]) <= 0.05)
wins = sum(1 for r in gate if r[6] > 0.05)
loss = sum(1 for r in gate if r[6] < -0.05)
print(f"样本外 GATE<=0.40 n={n}: 真赢(>0.05%)={wins}({100*wins/n:.0f}%) "
      f"保本(|pct|<=0.05)={be}({100*be/n:.0f}%) 真亏={loss}({100*loss/n:.0f}%)")
print(f"剔除保本后真实WR: {100*wins/(wins+loss):.0f}%")

# 保本单的risk0 vs 全体: 保本是不是窄止损的自然产物
be_r0 = [abs(r[4]-r[3])/r[3]*100 for r in gate if abs(r[6]) <= 0.05]
print(f"保本单risk0均值: {sum(be_r0)/len(be_r0):.3f}% (门槛内平均 "
      f"{sum(abs(r[4]-r[3])/r[3]*100 for r in gate)/n:.3f}%)")

# 赢单的R分布: 赢多深
win_ps = sorted(r[6] for r in gate if r[6] > 0.05)
if win_ps:
    import statistics
    print(f"真赢单pct: 中位={statistics.median(win_ps):+.2f}% 均值={statistics.mean(win_ps):+.2f}% "
          f"p90={win_ps[int(len(win_ps)*0.9)]:+.2f}%")

# 期望分解: 每笔期望 = 真赢贡献 + 真亏贡献
ew = sum(r[6] for r in gate if r[6] > 0.05) / n
el = sum(r[6] for r in gate if r[6] < -0.05) / n
print(f"期望分解: 真赢贡献 {ew:+.3f}%/笔 + 真亏贡献 {el:+.3f}%/笔 = {ew+el:+.3f}%/笔")
