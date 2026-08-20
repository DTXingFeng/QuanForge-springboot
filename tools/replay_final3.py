#!/usr/bin/env python3
"""重放 final3 账本, 用与引擎相同的 risk sizing 公式, 找出权益爆炸点"""
import sqlite3

con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_final3.db")
rows = con.execute("select created_at,settled_at,symbol,action,entry,stop_loss,take_profit,"
                   "status,result_pct,note from ai_advice_track "
                   "where status in ('WIN','LOSS') order by settled_at").fetchall()
eq = 200.0
RISK = 1.0
peak_trace = []
for k, (c_at, s_at, sym, act, entry, sl, tp, st, pct, note) in enumerate(rows):
    sl_pct = abs(entry - sl) / entry * 100
    base = min(eq * RISK / sl_pct, eq * 5.0) if sl_pct > 0.01 else eq * 5.0
    eq += base * pct / 100
    if eq > 1e6 and len(peak_trace) < 6:
        peak_trace.append((k, s_at, sym, act, entry, sl, sl_pct, st, pct, note, eq))
print("首次>1e6的时刻:")
for t in peak_trace:
    print(t)
# sl_pct 分布异常值
import collections
weird = [r for r in rows if abs(r[3] and abs(r[4] - r[5]) / r[4] * 100) > 50 or r[5] == 0]
print(f"\nsl_pct>50% 或 sl=0 的笔数: {len(weird)}")
for r in weird[:5]:
    print(r[2], r[3], "entry", r[4], "sl", r[5], "st", r[7], "pct", r[8], "note", r[9])
# pct 极值
mx = max(rows, key=lambda r: r[8])
mn = min(rows, key=lambda r: r[8])
print("\npct最大:", mx[2], mx[7], mx[8], mx[9])
print("pct最小:", mn[2], mn[7], mn[8], mn[9])
