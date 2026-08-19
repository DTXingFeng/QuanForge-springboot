#!/usr/bin/env python3
"""合并并行分段回测账本（seg_*.db -> merged.db）。
用法: python3 merge_backtest.py <prefix> <segs> <out_db>
  prefix = full / l0 / lat
  segs = 段数（6）
  out_db = 合并输出
"""
import sqlite3, sys, os

prefix, segs, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
log_dir = "/tmp/btp"
if os.path.exists(out):
    os.remove(out)
con = sqlite3.connect(out)
con.execute("""create table ai_advice_track(
    id integer primary key autoincrement, symbol text, action text,
    entry real, stop_loss real, take_profit real, status text,
    result_pct real, note text, sys_version text,
    created_at text, entered_at text, settled_at text, llm_ms integer)""")
n = 0
for k in range(segs):
    db = f"{log_dir}/seg_{prefix}_{k}.db"
    if not os.path.exists(db):
        print(f"seg{k} missing, skip")
        continue
    rows = sqlite3.connect(db).execute(
        "select symbol,action,entry,stop_loss,take_profit,status,result_pct,note,"
        "sys_version,created_at,entered_at,settled_at,llm_ms from ai_advice_track").fetchall()
    con.executemany("insert into ai_advice_track(symbol,action,entry,stop_loss,take_profit,"
                    "status,result_pct,note,sys_version,created_at,entered_at,settled_at,llm_ms)"
                    " values(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    n += len(rows)
    print(f"seg{k}: {len(rows)} rows")
con.commit()
con.close()
print(f"merged {n} rows -> {out}")
