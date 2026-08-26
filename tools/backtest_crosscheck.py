#!/usr/bin/env python3
"""前向假设的回测交叉验证: risk0分位 x 结果 + 连亏后下一笔期望"""
import sqlite3, collections

def agg(items):
    n = len(items)
    if not n:
        return "n=0"
    w = sum(1 for p in items if p > 0)
    return f"n={n:<5} WR={100*w/n:>4.0f}% 均笔={sum(items)/n:+.3f}% 和={sum(items):+.1f}pp"

for label, db in [("3R回测", "/mnt/nvme/quanforge/data/backtest_final3.db"),
                  ("5R回测", "/mnt/nvme/quanforge/data/backtest_final5.db")]:
    con = sqlite3.connect(db)
    rows = con.execute("select id, symbol, action, entry, stop_loss, result_pct, created_at "
                       "from ai_advice_track where status in ('WIN','LOSS') order by id").fetchall()
    con.close()
    print(f"\n===== {label} n={len(rows)} =====")

    print("[A] risk0 分位 x 结果:")
    r0s = sorted(abs(r[4] - r[3]) / r[3] * 100 for r in rows)
    q1, q2, q3 = r0s[len(r0s)//4], r0s[len(r0s)//2], r0s[3*len(r0s)//4]
    print(f"    分位线: 25%={q1:.3f} 50%={q2:.3f} 75%={q3:.3f}")
    by_r = collections.defaultdict(list)
    for r in rows:
        d = abs(r[4] - r[3]) / r[3] * 100
        b = (f"Q1窄<{q1:.2f}" if d < q1 else f"Q2{q1:.2f}-{q2:.2f}" if d < q2
             else f"Q3{q2:.2f}-{q3:.2f}" if d < q3 else f"Q4宽>={q3:.2f}")
        by_r[b].append(r[5])
    for b in sorted(by_r):
        print(f"    {b}%: {agg(by_r[b])}")

    print("[B] 连亏后下一笔期望:")
    by_s = collections.defaultdict(list)
    streak = 0
    for r in rows:
        by_s[min(streak, 3)].append(r[5])
        streak = streak + 1 if r[5] < 0 else 0
    for k in sorted(by_s):
        print(f"    前{k}连亏后: {agg(by_s[k])}")

    # C) 触发不可得, 但可看: risk0窄&5R 组合的连亏韧性
    if "5R" in label:
        print("[C] 5R Q1窄止损 的时间分布(按月):")
        by_m = collections.defaultdict(list)
        for r in rows:
            d = abs(r[4] - r[3]) / r[3] * 100
            if d < q1:
                by_m[r[6][:7]].append(r[5])
        for m in sorted(by_m):
            print(f"    {m}: {agg(by_m[m])}")
