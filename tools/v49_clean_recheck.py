#!/usr/bin/env python3
"""剔除泄露单(sl==entry)后重验risk0梯度 — 真实入场止损距离的边际"""
import sqlite3, math, collections

RISK, START = 1.0, 200.0

def stats(ps):
    n = len(ps)
    if not n:
        return None
    mean = sum(ps) / n
    var = sum((p - mean) ** 2 for p in ps) / max(n - 1, 1)
    return dict(n=n, wr=100 * sum(1 for p in ps if p > 0) / n, avg=mean,
                t=mean / math.sqrt(var / n) if var > 0 else 0)

for db, tag in [("/mnt/nvme/quanforge/data/backtest_final5.db", "5R回测"),
                ("/mnt/nvme/quanforge/data/backtest_final3.db", "3R回测"),
                ("/mnt/nvme/quanforge/data/paper_trendrule_tp5.db", "5R前向")]:
    con = sqlite3.connect(db)
    rows = con.execute(
        "select created_at, settled_at, symbol, entry, stop_loss, result_pct "
        "from ai_advice_track where status in ('WIN','LOSS') and entry>0 and stop_loss>0 "
        "order by settled_at").fetchall()
    con.close()
    # 剔泄露: sl==entry(保本后写库的未来函数)
    clean = [r for r in rows if abs(r[4] - r[3]) / r[3] * 100 >= 0.05]
    leak = len(rows) - len(clean)
    print(f"\n===== {tag} n={len(rows)} 剔泄露{leak} =====")
    bins = [("0.4-0.5", lambda d: 0.4 <= d < 0.5), ("0.5-0.6", lambda d: 0.5 <= d < 0.6),
            ("0.6-0.8", lambda d: 0.6 <= d < 0.8), ("0.8-1.0", lambda d: 0.8 <= d < 1.0),
            ("1.0-1.5", lambda d: 1.0 <= d < 1.5), (">=1.5", lambda d: d >= 1.5),
            ("全部(净)", lambda d: True)]
    for name, f in bins:
        ps = [r[5] for r in clean if f(abs(r[4] - r[3]) / r[3] * 100)]
        s = stats(ps)
        if s and s['n'] >= 5:
            print(f"  risk0 {name}%: {s['n']:<5} WR={s['wr']:.0f}% 均笔={s['avg']:+.3f}% t={s['t']:+.1f}")

    # 门槛模拟(净数据): 只交易risk0在某上限内
    print("  --- 门槛回放(净数据, risk sizing) ---")
    for gate in [0.5, 0.6, 0.8, None]:
        rs = [r for r in clean if gate is None or abs(r[4] - r[3]) / r[3] * 100 <= gate]
        if len(rs) < 10:
            continue
        s = stats([r[5] for r in rs])
        eq, peak, mdd = START, START, 0.0
        for r in rs:
            sl_pct = abs(r[4] - r[3]) / r[3] * 100
            base = min(eq * RISK / sl_pct, eq * 5.0)
            eq += base * r[5] / 100
            peak = max(peak, eq)
            mdd = min(mdd, (eq - peak) / peak * 100)
        g = f"<= {gate}%" if gate else "无门"
        print(f"    {g}: n={s['n']:<5} WR={s['wr']:.0f}% 均笔={s['avg']:+.3f}% t={s['t']:+.1f} "
              f"末权益={eq:.0f} maxDD={mdd:.1f}%")
