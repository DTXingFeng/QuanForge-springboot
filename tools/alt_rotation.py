#!/usr/bin/env python3
"""山寨集中度 + 轮换可行性:
1) 门槛之上 alts 分币x月 pnl — 集中度/持续性画像
2) 8月以外的生存力(去行情月后谁在赚钱)
3) 轮换信号: 前30天门槛内pnl 能否预测后30天 (Spearman + 分组对照)"""
import sqlite3
import numpy as np
import pandas as pd

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ACEUSDT", "ZECUSDT", "SNDKUSDT"]
ALTS = ["ACEUSDT", "ZECUSDT", "SNDKUSDT"]
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
D = []
for sym, ts, pct in rows:
    if sym not in ALTS:
        continue
    s = atr_s[sym]
    t = pd.Timestamp(ts)
    i = s.index.searchsorted(t, side="right") - 1
    if i < 400 or float(s.iloc[i]) < 0.32:
        continue
    D.append((sym, ts, pct))
D = pd.DataFrame(D, columns=["sym", "ts", "pct"])
D["month"] = D["ts"].str[:7]
D["t"] = pd.to_datetime(D["ts"])

print("== 1) 门槛之上 alts 分币x月 (累计% / 笔数) ==")
piv = D.pivot_table(index="sym", columns="month", values="pct", aggfunc="sum").round(0)
cnt = D.pivot_table(index="sym", columns="month", values="pct", aggfunc="count")
for sym in ALTS:
    line = f"{sym.replace('USDT',''):<6}"
    for m in piv.columns:
        v = piv.loc[sym, m]
        n = cnt.loc[sym, m]
        if pd.isna(v):
            line += f"  {m[-2:]}月    --"
        else:
            line += f"  {m[-2:]}月{v:+5.0f}%({int(n)})"
    print(line)

print("\n== 2) 8月以外各alt合计 ==")
for sym in ALTS:
    sub = D[(D["sym"] == sym) & (D["month"] != "2026-08")]
    w = len(sub[sub["pct"] > 0])
    print(f"{sym.replace('USDT',''):<6} n={len(sub):>4} WR={w/len(sub)*100 if len(sub) else 0:>4.0f}% "
          f"合计={sub['pct'].sum():+7.1f}%")

print("\n== 3) 轮换信号检验: 前30天pnl -> 后30天pnl ==")
pairs = []
for sym in ALTS:
    s_trades = D[D["sym"] == sym].sort_values("t")
    for anchor in pd.date_range("2026-03-01", "2026-08-01", freq="MS"):
        prev = s_trades[(s_trades["t"] >= anchor - pd.Timedelta(days=30)) &
                        (s_trades["t"] < anchor)]
        nxt = s_trades[(s_trades["t"] >= anchor) &
                       (s_trades["t"] < anchor + pd.Timedelta(days=30))]
        if len(prev) >= 5 and len(nxt) >= 5:
            pairs.append((sym, anchor.strftime("%m月"), prev["pct"].sum(), nxt["pct"].sum()))
P = pd.DataFrame(pairs, columns=["sym", "anchor", "prev", "next"])
print(P.to_string(index=False, float_format=lambda x: f"{x:+.1f}"))
if len(P) >= 6:
    from scipy.stats import spearmanr
    rho, p = spearmanr(P["prev"], P["next"])
    print(f"\nSpearman(prev30, next30) = {rho:+.2f} (p={p:.3f}, n={len(P)})")
# 对照: 每月选前30天最优1币 vs 持有全部3币
top_next, all_next = [], []
for anchor, grp in P.groupby("anchor"):
    best = grp.loc[grp["prev"].idxmax(), "sym"]
    top_next.append(P[(P["anchor"] == anchor) & (P["sym"] == best)]["next"].iloc[0])
    all_next.append(grp["next"].sum())
print(f"选前30天最优1币(次月): {np.sum(top_next):+.1f}% | 持有3币(次月): {np.sum(all_next):+.1f}%")
