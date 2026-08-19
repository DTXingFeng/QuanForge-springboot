#!/usr/bin/env python3
"""24小时盈亏分布 + 最差时段的币种构成"""
import sqlite3
from collections import defaultdict

con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest.db")
rows = con.execute("select symbol,action,created_at,result_pct from ai_advice_track "
                   "where status in ('WIN','LOSS')").fetchall()
hh = defaultdict(lambda: [0, 0, 0.0])
for sym, act, ts, pct in rows:
    h = int(ts[11:13])
    hh[h][0] += 1
    if pct > 0: hh[h][1] += 1
    hh[h][2] += pct
print("小时(UTC)  笔数  胜率   累计%")
for h in range(24):
    n, w, p = hh[h]
    print(f"{h:02d}:00     {n:>5}  {w/n*100 if n else 0:>4.0f}%  {p:>+7.1f}")

pos = sum(v[2] for v in hh.values() if v[2] > 0)
neg = sum(v[2] for v in hh.values() if v[2] < 0)
print(f"\n正时段合计 {pos:+.1f}%  负时段合计 {neg:+.1f}%  全月 {pos+neg:+.1f}%")

# 最差6个小时的币种构成
worst = sorted(hh.items(), key=lambda x: x[1][2])[:6]
wh = [h for h, _ in worst]
sym_h = defaultdict(float)
sym_n = defaultdict(int)
for sym, act, ts, pct in rows:
    if int(ts[11:13]) in wh:
        sym_h[sym] += pct; sym_n[sym] += 1
print(f"\n最差时段 {['%02d:00'%h for h in sorted(wh)]} 的币种构成:")
for sym in sorted(sym_h, key=sym_h.get):
    print(f"  {sym:<10} {sym_h[sym]:>+7.1f}%  (n={sym_n[sym]})")

# 假设砍掉最差6小时后的全月表现
kept = [(s, a, t, p) for s, a, t, p in rows if int(t[11:13]) not in wh]
w = len([r for r in kept if r[3] > 0])
print(f"\n砍掉后: n={len(kept)} WR={w/len(kept)*100:.1f}% 累计={sum(r[3] for r in kept):+.1f}%")

# 方向×时段
print("\nBUY vs SELL 分时段汇总（UTC 12h 块）:")
for lab, lo, hi in [("00-11", 0, 12), ("12-23", 12, 24)]:
    for d in ("BUY", "SELL"):
        rs = [p for s, a, t, p in rows if a == d and lo <= int(t[11:13]) < hi]
        if rs:
            ww = len([x for x in rs if x > 0])
            print(f"  {lab} {d:<4} n={len(rs):>4} WR={ww/len(rs)*100:.0f}% 累计={sum(rs):+.1f}%")
