#!/usr/bin/env python3
import sqlite3
from collections import defaultdict
con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_hm5.db")
rows = con.execute("select symbol,created_at,result_pct from ai_advice_track "
                   "where status in ('WIN','LOSS')").fetchall()
agg = defaultdict(float); cnt = defaultdict(int)
for sym, ts, pct in rows:
    k = (sym.replace("USDT", ""), ts[:7])
    agg[k] += pct; cnt[k] += 1
months = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
syms = ["ACE", "SNDK", "ZEC", "BTC", "ETH", "SOL"]
print("TP=5R 分币种x月 (累计%):")
print("      " + "".join(f"{m[-2:] + chr(26376):>9}" for m in months))
for s in syms:
    print(f"{s:<6}" + "".join(f"{agg.get((s, m), 0):>+9.0f}" for m in months))
