#!/usr/bin/env python3
"""ATR门槛 walk-forward: 逐月滚动 '用之前所有月定分位阈值 -> 下月验证'
对比固定0.32, 检验门槛参数的时序稳健性"""
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

def load_tp(tp):
    con = sqlite3.connect(f"/mnt/nvme/quanforge/data/backtest_hm{tp}.db")
    rows = con.execute("select symbol,created_at,result_pct from ai_advice_track "
                       "where status in ('WIN','LOSS')").fetchall()
    out = []
    for sym, ts, pct in rows:
        s = atr_s.get(sym)
        t = pd.Timestamp(ts)
        i = s.index.searchsorted(t, side="right") - 1
        if i < 400:
            continue
        out.append((ts[:7], float(s.iloc[i]), pct))
    return pd.DataFrame(out, columns=["month", "atr", "pct"])

MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
for tp in (3, 4, 5):
    D = load_tp(tp)
    print(f"\n== TP={tp}R walk-forward (训练分位=90%ile, 只用历史月) ==")
    cum_wf, cum_fix = 0.0, 0.0
    for m in MONTHS:
        hist = D[D["month"] < m]
        test = D[D["month"] == m]
        if hist.empty or test.empty:
            continue
        th = hist["atr"].quantile(0.9)
        keep = test[test["atr"] >= th]
        fix = test[test["atr"] >= 0.32]
        wf = keep["pct"].sum(); fx = fix["pct"].sum(); base = test["pct"].sum()
        cum_wf += wf; cum_fix += fx
        print(f"  验证{m}: 阈值{th:.3f} | 基线{base:+7.1f}% | WF门槛{wf:+7.1f}%(n={len(keep)}) "
              f"| 固定0.32 {fx:+7.1f}%(n={len(fix)})")
    print(f"  合计(6个月验证期): 基线{D['pct'].sum():+.1f}% | WF累计{cum_wf:+.1f}% | 固定0.32累计{cum_fix:+.1f}%")
