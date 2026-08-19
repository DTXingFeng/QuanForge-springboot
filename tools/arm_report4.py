#!/usr/bin/env python3
"""时段过滤的样本外验证: 前半月选最差小时 -> 后半月检验, 反之亦然"""
import sqlite3
from collections import defaultdict

con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest.db")
rows = [(s, a, t, p) for s, a, t, p in con.execute(
    "select symbol,action,created_at,result_pct from ai_advice_track where status in ('WIN','LOSS')")]
MID = "2026-08-04"

def hour_pnl(rs):
    hh = defaultdict(float)
    for _, _, t, p in rs: hh[int(t[11:13])] += p
    return hh

def worst_hours(rs, k=6):
    hh = hour_pnl(rs)
    return {h for h, _ in sorted(hh.items(), key=lambda x: x[1])[:k]}

def apply_keep(rs, block):
    kept = [r for r in rs if int(r[2][11:13]) not in block]
    w = len([r for r in kept if r[3] > 0])
    return len(kept), (w/len(kept)*100 if kept else 0), sum(r[3] for r in kept)

A = [r for r in rows if r[2] < MID]
B = [r for r in rows if r[2] >= MID]
for lab, train, test in [("前半月训练->后半月检验", A, B), ("后半月训练->前半月检验", B, A)]:
    wh = worst_hours(train)
    n0, wr0, p0 = apply_keep(test, set())      # 基线（不砍）
    n1, wr1, p1 = apply_keep(test, wh)          # 砍掉训练集选出的差时段
    print(f"{lab}")
    print(f"  训练集选出的差时段: {sorted('%02d:00'%h for h in wh)}")
    print(f"  检验集基线:   n={n0} WR={wr0:.1f}% 累计={p0:+.1f}%")
    print(f"  检验集砍时段: n={n1} WR={wr1:.1f}% 累计={p1:+.1f}%  (Δ{p1-p0:+.1f}%)")
    print()

# 对照: ACE 单独看. ACE全月 -12.7% (599笔) 是最大失血点, 砍时段后还剩多少
ace = [r for r in rows if r[0] == "ACEUSDT"]
wh_all = worst_hours(rows)
n1, wr1, p1 = apply_keep(ace, wh_all)
w0 = len([r for r in ace if r[3] > 0])
print(f"ACE 全月: n={len(ace)} WR={w0/len(ace)*100:.1f}% 累计={sum(r[3] for r in ace):+.1f}%")
print(f"ACE 砍全月差时段后: n={n1} WR={wr1:.1f}% 累计={p1:+.1f}%")

# ACE 的亏损集中在什么触发/方向?
ace_dir = defaultdict(lambda: [0, 0, 0.0])
for s, a, t, p in ace:
    ace_dir[a][0] += 1
    if p > 0: ace_dir[a][1] += 1
    ace_dir[a][2] += p
for a, (n, w, pp) in ace_dir.items():
    print(f"ACE {a}: n={n} WR={w/n*100:.0f}% 累计={pp:+.1f}%")
