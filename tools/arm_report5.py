#!/usr/bin/env python3
import sqlite3
con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest.db")
q = "select action,created_at,result_pct from ai_advice_track where status in ('WIN','LOSS') and symbol=?"
for sym in ("ACEUSDT", "SNDKUSDT"):
    for d in ("SELL", "BUY"):
        for lab, lo, hi in [("7/19-8/4", "2026-07-19", "2026-08-04"), ("8/4-8/19", "2026-08-04", "2027-01-01")]:
            rs = [r[2] for r in con.execute(q + " and action=? and created_at>=? and created_at<?", (sym, d, lo, hi))]
            if rs:
                w = len([x for x in rs if x > 0])
                print(f"{sym:<9} {d:<4} {lab}: n={len(rs):>3} WR={w/len(rs)*100:>4.0f}% 累计={sum(rs):+.1f}%")
k = sqlite3.connect("/mnt/nvme/quanforge/data/kline_1m.db")
for sym in ("ACEUSDT", "SNDKUSDT", "BTCUSDT"):
    try:
        first = k.execute(f"select close from {sym} where startTime=(select min(startTime) from {sym} where startTime>='2026-07-19')").fetchone()
        mid = k.execute(f"select close from {sym} where startTime=(select min(startTime) from {sym} where startTime>='2026-08-04')").fetchone()
        last = k.execute(f"select close from {sym} order by startTime desc limit 1").fetchone()
        print(f"{sym} 收盘: 7/19={first[0]:.4f}  8/4={mid[0]:.4f}  8/19={last[0]:.4f}  (8月涨跌 {(last[0]/mid[0]-1)*100:+.1f}%)")
    except Exception as e:
        print(sym, "kline err", e)
