#!/usr/bin/env python3
"""v4.9 walk-forward: 前4个月选risk0门槛, 后3个月样本外验证 — 防全样本拟合"""
import sqlite3, math, collections

RISK, START = 1.0, 200.0
SPLIT = "2026-06"   # 6月起为样本外

con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_final5.db")
rows = con.execute(
    "select created_at, settled_at, symbol, action, entry, stop_loss, result_pct "
    "from ai_advice_track where status in ('WIN','LOSS') order by settled_at").fetchall()
con.close()
rows = [r for r in rows if r[4] and r[5] and r[4] > 0 and r[5] > 0]

def stats(rs):
    n = len(rs)
    if not n:
        return None
    ps = [r[6] for r in rs]
    mean = sum(ps) / n
    var = sum((p - mean) ** 2 for p in ps) / max(n - 1, 1)
    return dict(n=n, wr=100 * sum(1 for p in ps if p > 0) / n, avg=mean,
                t=mean / math.sqrt(var / n) if var > 0 else 0)

def eq_curve(rs):
    eq, peak, mdd = START, START, 0.0
    for r in rs:
        sl_pct = abs(r[4] - r[5]) / r[4] * 100
        base = min(eq * RISK / sl_pct, eq * 5.0) if sl_pct > 0.01 else eq * 5.0
        eq += base * r[6] / 100
        peak = max(peak, eq)
        mdd = min(mdd, (eq - peak) / peak * 100)
    return eq, mdd

train = [r for r in rows if r[1][:7] < SPLIT]
test = [r for r in rows if r[1][:7] >= SPLIT]
print(f"训练集(2-5月): {len(train)}笔 | 样本外(6-8月): {len(test)}笔")

print("\n[训练集] 各门槛 t 值(选最大):")
best = None
for gate in [0.40, 0.435, 0.45, 0.475, 0.50, 0.55, 0.60, 0.80]:
    s = stats([r for r in train if abs(r[5] - r[4]) / r[4] * 100 <= gate])
    if s:
        print(f"  GATE={gate:.3f}%: n={s['n']:<4} WR={s['wr']:.0f}% 均笔={s['avg']:+.3f}% t={s['t']:+.1f}")
        if best is None or s['t'] > best[1]['t']:
            best = (gate, s)
print(f"训练集最优门槛: {best[0]}% (t={best[1]['t']:+.1f})")

print("\n[样本外 6-8月] 训练选出的门槛 vs 裸臂:")
for tag, gate in [(f"训练选优 {best[0]}%", best[0]), ("裸臂(无门)", None)]:
    rs = [r for r in test if gate is None or abs(r[5] - r[4]) / r[4] * 100 <= gate]
    s = stats(rs)
    eq, mdd = eq_curve(rs)
    ps = sorted(set(r[2] for r in rs))
    print(f"  {tag}: n={s['n']} WR={s['wr']:.0f}% 均笔={s['avg']:+.3f}% t={s['t']:+.1f} "
          f"3个月权益 {START:.0f}->{eq:.1f} maxDD={mdd:.1f}% 币种={ps}")

# 分月样本外
print("\n[样本外分月]:")
for m in sorted(set(r[1][:7] for r in test)):
    for tag, gate in [(f"GATE={best[0]}", best[0]), ("裸臂", None)]:
        rs = [r for r in test if r[1][:7] == m and
              (gate is None or abs(r[5] - r[4]) / r[4] * 100 <= gate)]
        s = stats(rs)
        if s:
            print(f"  {m} {tag:12s}: n={s['n']:<4} WR={s['wr']:.0f}% 均笔={s['avg']:+.3f}%")
