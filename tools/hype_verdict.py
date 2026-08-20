#!/usr/bin/env python3
"""HYPE 6个月 trend-rule 5R 验证: 合并seg + 门槛上下分解 + 逐月"""
import sqlite3, subprocess
import numpy as np
import pandas as pd

out = "/mnt/nvme/quanforge/data/backtest_hype.db"
subprocess.run(["python3", "/mnt/nvme/quanforge/tools/merge_backtest.py",
                "hype", "6", out], capture_output=True)

kcon = sqlite3.connect("/mnt/nvme/quanforge/data/quanforge.db")
df = pd.read_sql_query(
    "select open_time,high,low,close from kline_1m where symbol='HYPEUSDT' "
    "and open_time>=1771000000000 order by open_time", kcon)
df.index = pd.to_datetime(df["open_time"], unit="ms")
c, h, l = df["close"], df["high"], df["low"]
pc = c.shift()
tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
atr_s = (tr.ewm(alpha=1/14, adjust=False).mean() / c * 100).astype("float32")

con = sqlite3.connect(out)
rows = con.execute("select created_at,result_pct from ai_advice_track "
                   "where status in ('WIN','LOSS') order by created_at").fetchall()
kept, blocked = [], []
by_month = {}
for ts, pct in rows:
    t = pd.Timestamp(ts)
    i = atr_s.index.searchsorted(t, side="right") - 1
    ok = i >= 400 and float(atr_s.iloc[i]) >= 0.32
    (kept if ok else blocked).append((ts, pct))
    m = ts[:7]
    d = by_month.setdefault(m, [0, 0.0])
    if ok:
        d[0] += 1; d[1] += pct

n = len(kept); w = len([1 for _, p in kept if p > 0])
print(f"HYPE 门槛内: n={n} WR={w/n*100 if n else 0:.1f}% 累计={sum(p for _,p in kept):+.1f}% "
      f"均笔={sum(p for _,p in kept)/n if n else 0:+.4f}%")
print(f"HYPE 被拦:   n={len(blocked)} 累计={sum(p for _,p in blocked):+.1f}%")
print("门槛内逐月: " + "  ".join(f"{m}:{v[1]:+.0f}%({v[0]})" for m, v in sorted(by_month.items())))
