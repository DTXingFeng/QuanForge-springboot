#!/usr/bin/env python3
"""6个月矩阵判决: TP∈{3,4,5} x 6个30天窗 (固定$1000仓)"""
import sqlite3
from collections import defaultdict

for tp in (3, 4, 5):
    db = f"/mnt/nvme/quanforge/data/backtest_hm{tp}.db"
    con = sqlite3.connect(db)
    rows = con.execute("select symbol,action,status,result_pct,created_at from ai_advice_track "
                       "where status in ('WIN','LOSS') order by created_at").fetchall()
    # 按30天段(k=0最近 -> k=5最远)与日历月双口径
    import datetime
    base = datetime.datetime(2026, 8, 19)
    segs = defaultdict(lambda: [0, 0, 0.0])
    months = defaultdict(lambda: [0, 0, 0.0])
    eq = 200.0
    peak, mdd = 200.0, 0.0
    for sym, act, st, pct, ts in rows:
        t = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        k = int((base - t).days // 30)
        segs[k][0] += 1; segs[k][2] += pct
        months[t.strftime("%Y-%m")][0] += 1; months[t.strftime("%Y-%m")][2] += pct
        if st == "WIN":
            segs[k][1] += 1; months[t.strftime("%Y-%m")][1] += 1
        eq += 10 * pct
        peak = max(peak, eq); mdd = max(mdd, peak - eq)
    n = len(rows); w = sum(1 for r in rows if r[2] == "WIN")
    gp = sum(r[3] for r in rows if r[3] > 0); gl = abs(sum(r[3] for r in rows if r[3] < 0))
    print(f"\n===== TP={tp}R  总计: n={n} WR={w/n*100:.1f}% PF={gp/gl:.2f} "
          f"6段合计={sum(r[3] for r in rows):+.1f}% (终值 {eq:.0f}/1200) 最大回撤${mdd:.0f}")
    print("  按30天段(0=最近): " + "  ".join(
        f"[{k}] {segs[k][2]:+.0f}%({segs[k][0]})" for k in sorted(segs)))
    print("  按日历月:        " + "  ".join(
        f"{m} {v[2]:+.0f}%({v[0]})" for m, v in sorted(months.items())))
    # 分币种
    sy = defaultdict(lambda: [0, 0, 0.0])
    for sym, act, st, pct, ts in rows:
        sy[sym][0] += 1; sy[sym][2] += pct
        if st == "WIN": sy[sym][1] += 1
    print("  分币种: " + "  ".join(
        f"{s.replace('USDT','')} {v[2]:+.0f}%/{v[0]}笔({v[1]/v[0]*100:.0f}%)" for s, v in sorted(sy.items())))
