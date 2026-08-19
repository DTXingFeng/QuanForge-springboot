#!/usr/bin/env python3
import sqlite3
con = sqlite3.connect("/mnt/nvme/quanforge/data/quanforge.db")
for r in con.execute("select sys_version,status,count(*) from ai_advice_track "
                     "where created_at > datetime('now','-2 day') group by sys_version,status"):
    print(r)
print("--- positions open now ---")
for r in con.execute("select symbol,action,status,entry,created_at from ai_advice_track "
                     "where status in ('PENDING','ENTERED') order by created_at desc limit 8"):
    print(r)
