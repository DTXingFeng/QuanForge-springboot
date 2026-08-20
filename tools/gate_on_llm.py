#!/usr/bin/env python3
"""ATR门槛 x LLM臂: 同一门槛(0.32)后验过滤 full/live 账本, 检验 regime 发现普适性"""
import sqlite3
import numpy as np
import pandas as pd

TRAIN_END = "2026-06-01"
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

def load(db):
    con = sqlite3.connect(db)
    rows = con.execute("select symbol,created_at,result_pct from ai_advice_track "
                       "where status in ('WIN','LOSS')").fetchall()
    out = []
    for sym, ts, pct in rows:
        s = atr_s.get(sym)
        if s is None:
            continue
        t = pd.Timestamp(ts)
        i = s.index.searchsorted(t, side="right") - 1
        if i < 400:
            continue
        out.append((ts < TRAIN_END, float(s.iloc[i]), pct))
    return pd.DataFrame(out, columns=["train", "atr", "pct"])

for label, db in [("full(零延迟LLM)", "/mnt/nvme/quanforge/data/backtest.db"),
                  ("live(生产LLM)", "/mnt/nvme/quanforge/data/backtest_live.db")]:
    D = load(db)
    if D.empty:
        print(label, "无数据"); continue
    keep = D[D["atr"] >= 0.32]
    ktr, kte = keep[keep["train"]]["pct"].sum(), keep[~keep["train"]]["pct"].sum()
    btr, bte = D[D["train"]]["pct"].sum(), D[~D["train"]]["pct"].sum()
    print(f"{label:<14} 基线: 训练{btr:+7.1f}% 测试{bte:+7.1f}% 总{D['pct'].sum():+7.1f}% (n={len(D)})")
    print(f"{'':<14} 门槛: 训练{ktr:+7.1f}% 测试{kte:+7.1f}% 总{keep['pct'].sum():+7.1f}% "
          f"(n={len(keep)}, 留存{len(keep)/len(D)*100:.0f}%)")
    w_all = len(D[D['pct'] > 0]); w_keep = len(keep[keep['pct'] > 0])
    print(f"{'':<14} WR: 基线{w_all/len(D)*100:.1f}% -> 门槛{w_keep/len(keep)*100:.1f}%")
