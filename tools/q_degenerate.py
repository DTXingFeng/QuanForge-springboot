#!/usr/bin/env python3
import sqlite3
con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_final3.db")
print("总行数:", con.execute("select count(*) from ai_advice_track").fetchone()[0])
print("按version:", con.execute("select sys_version,count(*) from ai_advice_track group by sys_version").fetchall())
q = ("select count(*) from ai_advice_track where status in ('WIN','LOSS') "
     "and (take_profit=0 or stop_loss=0 or abs(entry-stop_loss)/entry*100<=0.01)")
print("WIN/LOSS中退化SL(tp=0或sl=0或sl距离<=0.01%):", con.execute(q).fetchone()[0])
for r in con.execute("select symbol,action,entry,stop_loss,take_profit,status,result_pct,"
                     "sys_version,created_at,note from ai_advice_track "
                     "where status in ('WIN','LOSS') and take_profit=0 limit 5"):
    print(r)
