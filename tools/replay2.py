#!/usr/bin/env python3
"""在干净final3库上重放risk sizing, 打印权益跳变最大的10笔"""
import sqlite3

con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_final3.db")
print("版本分布:", con.execute("select sys_version,count(*) from ai_advice_track group by sys_version").fetchall())
rows = con.execute("select settled_at,symbol,action,entry,stop_loss,take_profit,"
                   "status,result_pct,note from ai_advice_track "
                   "where status in ('WIN','LOSS') order by settled_at, id").fetchall()
print("WIN/LOSS笔数:", len(rows))
eq = 200.0
jumps = []
for k, (s_at, sym, act, entry, sl, tp, st, pct, note) in enumerate(rows):
    sl_pct = abs(entry - sl) / entry * 100
    base = min(eq * 1.0 / sl_pct, eq * 5.0) if sl_pct > 0.01 else eq * 5.0
    new_eq = eq + base * pct / 100
    jumps.append((abs(new_eq / eq - 1), k, s_at, sym, act, sl_pct, st, pct, note, new_eq))
    eq = new_eq
print("终值:", eq)
jumps.sort(reverse=True)
print("\n权益跳变Top10:")
for j in jumps[:10]:
    print(f"  jump={j[0]*100:7.1f}%  #{j[1]} {j[2]} {j[3]} {j[4]} sl%={j[5]:.3f} "
          f"{j[6]} pct={j[7]:+.2f} note={j[8]!r} eq->{j[9]:.1f}")
small = [j for j in jumps if j[5] <= 0.05]
print(f"\nsl%<=0.05的笔数: {len(small)}")
