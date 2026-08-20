#!/usr/bin/env python3
"""majors 去留决策: 门槛(ATR>=0.32)之上 majors vs alts 分解, 跨 TP=3/4/5 验证
另附: TTL平仓占比(门槛上单子有多少死于TTL而非SL/TP)"""
import sqlite3
import numpy as np
import pandas as pd

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ACEUSDT", "ZECUSDT", "SNDKUSDT"]
MAJORS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
kcon = sqlite3.connect("/mnt/nvme/quanforge/data/quanforge.db")
atr_s = {}
for sym in SYMBOLS:
    df = pd.read_sql_query(
        f"select open_time,high,low,close from kline_1m where symbol='{sym}' "
        f"and open_time>=1771000000000 order by open_time", kcon)
    df.index = pd.to_datetime(df["open_time"], unit="ms")
    c, h, l = df["close"], df["high"], df["low"]
    pc = c.shift()
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    atr_s[sym] = (tr.ewm(alpha=1/14, adjust=False).mean() / c * 100).astype("float32")

print("== 门槛之上(ATR>=0.32): majors 合计 vs alts 合计, 跨TP ==")
for tp in (3, 4, 5):
    con = sqlite3.connect(f"/mnt/nvme/quanforge/data/backtest_hm{tp}.db")
    rows = con.execute("select symbol,created_at,result_pct,note from ai_advice_track "
                       "where status in ('WIN','LOSS')").fetchall()
    agg = {"majors": [0, 0.0], "alts": [0, 0.0]}
    ttl = {"majors": [0, 0], "alts": [0, 0]}
    for sym, ts, pct, note in rows:
        s = atr_s.get(sym)
        t = pd.Timestamp(ts)
        i = s.index.searchsorted(t, side="right") - 1
        if i < 400 or float(s.iloc[i]) < 0.32:
            continue
        grp = "majors" if sym in MAJORS else "alts"
        agg[grp][0] += 1; agg[grp][1] += pct
        ttl[grp][1] += 1
        if note and "TTL" in note:
            ttl[grp][0] += 1
    m, a = agg["majors"], agg["alts"]
    print(f"TP={tp}R: majors n={m[0]:>4} {m[1]:>+7.1f}% (TTL死 {ttl['majors'][0]}/{ttl['majors'][1]})"
          f" | alts n={a[0]:>4} {a[1]:>+7.1f}% (TTL死 {ttl['alts'][0]}/{ttl['alts'][1]})")
