#!/usr/bin/env python3
"""审计: 全局0.32门槛的分币种通过率 — 它到底拦了谁?
若 majors 全被拦 -> 门槛=事实上的'只做山寨', 需考虑分币种分位门槛对照"""
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

con = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_hm5.db")
rows = con.execute("select symbol,created_at,result_pct from ai_advice_track "
                   "where status in ('WIN','LOSS')").fetchall()

from collections import defaultdict
per = defaultdict(lambda: [0, 0, 0.0, 0.0])   # sym: [total, kept, pnl_kept, pnl_blocked]
atr_by_sym = defaultdict(list)
for sym, ts, pct in rows:
    s = atr_s.get(sym)
    t = pd.Timestamp(ts)
    i = s.index.searchsorted(t, side="right") - 1
    if i < 400:
        continue
    a = float(s.iloc[i])
    atr_by_sym[sym].append(a)
    d = per[sym]
    d[0] += 1
    if a >= 0.32:
        d[1] += 1; d[2] += pct
    else:
        d[3] += pct

print(f"{'币种':<9}{'总笔数':>6}{'通过率':>8}{'ATR中位':>9}{'门槛内pnl':>10}{'被拦pnl':>10}")
for sym in SYMBOLS:
    d = per[sym]
    med = float(np.median(atr_by_sym[sym]))
    print(f"{sym:<9}{d[0]:>6}{d[1]/d[0]*100:>7.0f}%{med:>8.3f}%{d[2]:>+10.1f}%{d[3]:>+10.1f}%")

# 对照: 分币种相对分位门槛(该币自身ATR分布70分位), 是否更优?
print("\n== 对照实验: 分币种相对门槛(自身70分位) vs 全局0.32 ==")
q70 = {sym: float(np.quantile(atr_by_sym[sym], 0.7)) for sym in SYMBOLS}
print("各币70分位ATR%:", {s.replace("USDT", ""): round(v, 3) for s, v in q70.items()})
tot_abs, tot_rel = 0.0, 0.0
n_abs = n_rel = 0
for sym, ts, pct in rows:
    s = atr_s.get(sym)
    t = pd.Timestamp(ts)
    i = s.index.searchsorted(t, side="right") - 1
    if i < 400:
        continue
    a = float(s.iloc[i])
    if a >= 0.32:
        tot_abs += pct; n_abs += 1
    if a >= q70[sym]:
        tot_rel += pct; n_rel += 1
print(f"全局0.32:   n={n_abs} 累计={tot_abs:+.1f}%")
print(f"相对70分位: n={n_rel} 累计={tot_rel:+.1f}%")
