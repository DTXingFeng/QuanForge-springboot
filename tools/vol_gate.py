#!/usr/bin/env python3
"""波动率门槛测试: 只在 ATR% >= 阈值 时交易, 其余触发放弃.
用 hm5 joined 数据, 逐阈值 x 逐月报 留存笔数/累计pnl"""
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

bcon = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_hm5.db")
trades = bcon.execute("select symbol,created_at,result_pct,status from ai_advice_track "
                      "where status in ('WIN','LOSS') order by created_at").fetchall()
rows = []
for sym, ts, pct, st in trades:
    s = atr_s.get(sym)
    t = pd.Timestamp(ts)
    i = s.index.searchsorted(t, side="right") - 1
    if i < 400:
        continue
    rows.append((ts, float(s.iloc[i]), pct))
T = pd.DataFrame(rows, columns=["ts", "atr", "pct"])
T["month"] = T["ts"].str[:7]
T["train"] = T["ts"] < TRAIN_END

# ===== 跨TP稳健性: 同一门槛(0.32, 训练期90分位)套到 hm3/hm4/hm5 =====
for tp in (3, 4, 5):
    con = sqlite3.connect(f"/mnt/nvme/quanforge/data/backtest_hm{tp}.db")
    rs = con.execute("select symbol,created_at,result_pct from ai_advice_track "
                     "where status in ('WIN','LOSS')").fetchall()
    out = []
    for sym, ts, pct in rs:
        s = atr_s.get(sym)
        t = pd.Timestamp(ts)
        i = s.index.searchsorted(t, side="right") - 1
        if i < 400:
            continue
        out.append((ts < TRAIN_END, float(s.iloc[i]), pct))
    D = pd.DataFrame(out, columns=["train", "atr", "pct"])
    for th in (0.32,):
        keep = D[D["atr"] >= th]
        ktr, kte = keep[keep["train"]]["pct"].sum(), keep[~keep["train"]]["pct"].sum()
        print(f"TP={tp}R 门槛{th}: 总{keep['pct'].sum():+7.1f}% "
              f"(基线{D['pnl'].sum() if False else D['pct'].sum():+7.1f}%) 训练{ktr:+6.1f}% 测试{kte:+6.1f}% "
              f"留存{len(keep)/len(D)*100:.0f}%")

base = T.groupby("month")["pct"].agg(["size", "sum"]).round(1)
print("基线(无门槛) 逐月: 笔数 / 累计%")
print(base.to_string(), "\n总:", round(T["pct"].sum(), 1), "%\n")

# 训练期(2-5月)可见的候选阈值: 训练期ATR分布的 50/70/80/90 分位
qs = T[T["train"]]["atr"].quantile([0.5, 0.7, 0.8, 0.9]).round(3)
print("训练期ATR分位(候选门槛):", dict(qs), "\n")
for th in list(qs.values) + [0.30, 0.35, 0.40]:
    sub = T[T["atr"] >= th]
    tr_p, te_p = sub[sub["train"]]["pct"].sum(), sub[~sub["train"]]["pct"].sum()
    by_month = sub.groupby("month")["pct"].agg(["size", "sum"]).round(1)
    kept = len(sub) / len(T) * 100
    print(f"门槛 ATR>={th:.2f}%: 留存{kept:.0f}% 笔 | 训练期{tr_p:+.0f}% 测试期{te_p:+.0f}% | "
          f"总{sub['pct'].sum():+.0f}%")
    print("   " + "  ".join(f"{m}:{v['sum']:+.0f}%({int(v['size'])})" for m, v in by_month.iterrows()))
