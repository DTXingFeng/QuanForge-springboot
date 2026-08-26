#!/usr/bin/env python3
"""查回测库risk0分布: 是否大量stop_loss==entry(保本泄露)"""
import sqlite3, collections

for db in ["/mnt/nvme/quanforge/data/backtest_final5.db",
           "/mnt/nvme/quanforge/data/paper_trendrule_tp5.db"]:
    con = sqlite3.connect(db)
    rows = con.execute(
        "select entry, stop_loss, result_pct, status from ai_advice_track "
        "where status in ('WIN','LOSS') and entry is not null and stop_loss is not null "
        "and entry > 0 and stop_loss > 0").fetchall()
    con.close()
    bins = collections.Counter()
    zero = 0
    for e, sl, p, st in rows:
        d = abs(sl - e) / e * 100
        if d < 0.005:
            zero += 1
        b = ("<0.05" if d < 0.05 else "0.05-0.2" if d < 0.2 else "0.2-0.4" if d < 0.4
             else "0.4-0.6" if d < 0.6 else "0.6-1.0" if d < 1.0 else "1.0-2.0" if d < 2.0 else ">=2.0")
        bins[b] += 1
    n = len(rows)
    print(f"\n{db.split('/')[-1]} n={n}  sl==entry(泄露特征)={zero} ({100*zero/n:.0f}%)")
    for b in ["<0.05", "0.05-0.2", "0.2-0.4", "0.4-0.6", "0.6-1.0", "1.0-2.0", ">=2.0"]:
        print(f"  risk0 {b}%: {bins.get(b,0):>5} ({100*bins.get(b,0)/n:.0f}%)")
