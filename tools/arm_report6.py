#!/usr/bin/env python3
"""ACE/SNDK 空单入场时的趋势对齐检验:
亏损空单在入场时刻, 15m/1h EMA 趋势是 UP(逆势做空) 还是 DOWN(顺势做空)?
若顺势也亏 -> 1h过滤没用, 需要禁空; 若逆势集中 -> 过滤可救"""
import sqlite3, glob
import pandas as pd

DATA = glob.glob("/mnt/nvme/quanforge/data/kline*.db")[0] \
    if glob.glob("/mnt/nvme/quanforge/data/kline*.db") else None
# 找对 kline 库: 表名带 USDT
cands = glob.glob("/mnt/nvme/quanforge/data/*.db")
print("db files:", [c.split("/")[-1] for c in cands])

kcon, kdb = None, None
for c in cands:
    con = sqlite3.connect(c)
    tabs = [t[0] for t in con.execute("select name from sqlite_master where type='table'")]
    if "kline_1m" in tabs:
        kcon, kdb = con, c
        break
if kcon is None:
    raise SystemExit("no kline db found")
print("kline db:", kdb)

def load(sym):
    df = pd.read_sql(f"select open_time,open,high,low,close from kline_1m "
                     f"where symbol='{sym}' and open_time>=1784448000000 order by open_time", kcon)
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms")
    return df.set_index("ts")

bcon = sqlite3.connect("/mnt/nvme/quanforge/data/backtest.db")

for sym in ("ACEUSDT", "SNDKUSDT"):
    df = load(sym)
    c = df["close"]
    # 与回测一致: EMA20/60 (1m) 及 EMA60/200 (1m) 代理 15m/1h
    ema20 = c.ewm(span=20).mean(); ema60 = c.ewm(span=60).mean(); ema200 = c.ewm(span=200).mean()
    rows = bcon.execute("select action,created_at,result_pct from ai_advice_track "
                        "where status in ('WIN','LOSS') and symbol=? order by created_at", (sym,)).fetchall()
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0, 0.0])
    for act, ts, pct in rows:
        t = pd.Timestamp(ts)
        if len(df) == 0 or t < df.index[0]:
            continue
        if t not in df.index:
            pos_i = df.index.searchsorted(t, side="right") - 1
            if pos_i < 0:
                continue
            t = df.index[pos_i]
        t15 = "UP" if ema20.loc[t] > ema60.loc[t] else "DOWN"
        t1h = "UP" if ema60.loc[t] > ema200.loc[t] else "DOWN"
        if act == "SELL":
            key = f"SELL 15m{t15[:1]}h1{['D' if t1h=='DOWN' else 'U'][0]}"  # SELL顺势=两线DOWN
            align = "顺势" if (t15 == "DOWN" and t1h == "DOWN") else \
                    ("半逆" if (t15 == "DOWN" or t1h == "DOWN") else "全逆")
        else:
            align = "顺势" if (t15 == "UP" and t1h == "UP") else \
                    ("半逆" if (t15 == "UP" or t1h == "UP") else "全逆")
        k = f"{act} {align}"
        agg[k][0] += 1
        if pct > 0: agg[k][1] += 1
        agg[k][2] += pct
    print(f"\n== {sym} ==")
    for k in sorted(agg):
        n, w, p = agg[k]
        print(f"  {k:<12} n={n:>4}  WR={w/n*100:>4.0f}%  累计={p:>+7.1f}%")
