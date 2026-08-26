#!/usr/bin/env python3
"""risk0门槛敏感性: 5R回测在不同阈值下的表现 + 分symbol + 与频率"""
import sqlite3, collections

def agg(items):
    n = len(items)
    if not n:
        return "n=0"
    w = sum(1 for p in items if p > 0)
    return f"n={n:<5} WR={100*w/n:>4.0f}% 均笔={sum(items)/n:+.3f}% 和={sum(items):+.1f}pp"

con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_final5.db")
rows = con.execute("select symbol, action, entry, stop_loss, result_pct, created_at "
                   "from ai_advice_track where status in ('WIN','LOSS') order by id").fetchall()
con.close()

print("[5R回测] risk0阈值敏感性:")
for th in [0.35, 0.40, 0.435, 0.50, 0.55, 0.60, 0.80, 99]:
    xs = [r[4] for r in rows if abs(r[3] - r[2]) / r[2] * 100 <= th]
    label = f"<={th:.3f}%" if th < 90 else "全部"
    print(f"  {label}: {agg(xs)}")

print("\n[5R回测] risk0<=0.50 分symbol:")
by = collections.defaultdict(list)
for r in rows:
    if abs(r[3] - r[2]) / r[2] * 100 <= 0.50:
        by[r[0]].append(r[4])
for k in sorted(by):
    print(f"  {k}: {agg(by[k])}")

print("\n[5R回测] risk0<=0.50 按月(频率+期望):")
by_m = collections.defaultdict(list)
for r in rows:
    if abs(r[3] - r[2]) / r[2] * 100 <= 0.50:
        by_m[r[5][:7]].append(r[4])
tot_days = 189  # 2026-02~08 约6.2个月
for m in sorted(by_m):
    xs = by_m[m]
    print(f"  {m}: {agg(xs)}  (~{len(xs)/30:.1f}笔/天)")

print("\n[对照] 3R回测 risk0<=0.50:")
con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_final3.db")
rows3 = con.execute("select entry, stop_loss, result_pct from ai_advice_track "
                    "where status in ('WIN','LOSS')").fetchall()
con.close()
xs = [r[2] for r in rows3 if abs(r[1] - r[0]) / r[0] * 100 <= 0.50]
print(f"  <=0.50%: {agg(xs)}")
