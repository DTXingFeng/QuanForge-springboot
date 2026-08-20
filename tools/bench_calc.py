#!/usr/bin/env python3
"""从hm3/hm5+ATR join 计算门槛后真实基准(WR/均笔/频率), 供paper_status对照"""
import sqlite3
import numpy as np
import pandas as pd

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ACEUSDT", "ZECUSDT", "SNDKUSDT"]
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

for tp in (3, 5):
    con = sqlite3.connect(f"/mnt/nvme/quanforge/data/backtest_hm{tp}.db")
    rows = con.execute("select symbol,created_at,result_pct from ai_advice_track "
                       "where status in ('WIN','LOSS')").fetchall()
    kept = []
    for sym, ts, pct in rows:
        s = atr_s.get(sym)
        t = pd.Timestamp(ts)
        i = s.index.searchsorted(t, side="right") - 1
        if i < 400:
            continue
        if float(s.iloc[i]) >= 0.32:
            kept.append((ts, pct))
    days = 195  # 6.5个月窗口
    n = len(kept); w = len([1 for _, p in kept if p > 0]); tot = sum(p for _, p in kept)
    print(f"TP={tp}R gate0.32 基准: n={n} WR={w/n*100:.1f}% 均笔={tot/n:+.4f}% "
          f"累计={tot:+.1f}% 频率={n/days:.1f}笔/天")
