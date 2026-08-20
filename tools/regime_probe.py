#!/usr/bin/env python3
"""regime 病根探针: 用 hm5 (trend-rule 5R, 10520笔) 检验市场状态特征能否分离盈亏月.
特征全部 point-in-time (只用当 bar 及以前数据):
  er60     Kaufman效率比 60min (趋势质量: 净位移/路径长度)
  atr_pct  ATR14% (波动水平)
  bbw      布林带宽(20,2sd)/close (波动压缩/扩张)
  trend_age EMA20/60/200 对齐持续分钟数 (对齐翻转=趋势转换)
  d_align  与日线代理EMA(1440)方向一致 (1/0)
判定: 分位数分桶(分位线只用训练期2-5月算) -> 训练/测试期分开报 WR/累计
"""
import sqlite3
import numpy as np
import pandas as pd

TRAIN_END = "2026-06-01"     # 2-5月训练, 6-8月测试
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ACEUSDT", "ZECUSDT", "SNDKUSDT"]
PROD = "/mnt/nvme/quanforge/data/quanforge.db"
BT = "/mnt/nvme/quanforge/data/backtest_hm5.db"

kcon = sqlite3.connect(PROD)
feat = {}
for sym in SYMBOLS:
    df = pd.read_sql_query(
        f"select open_time,open,high,low,close,volume from kline_1m where symbol='{sym}' "
        f"and open_time>=1771000000000 order by open_time", kcon)
    df.index = pd.to_datetime(df["open_time"], unit="ms")
    c = df["close"]
    f = pd.DataFrame(index=df.index)
    # Kaufman ER60
    net = (c - c.shift(60)).abs()
    path = c.diff().abs().rolling(60).sum()
    f["er60"] = (net / path.replace(0, np.nan)).fillna(0)
    # ATR%
    pc = c.shift()
    tr = pd.concat([df["high"]-df["low"], (df["high"]-pc).abs(),
                    (df["low"]-pc).abs()], axis=1).max(axis=1)
    f["atr_pct"] = (tr.ewm(alpha=1/14, adjust=False).mean() / c * 100)
    # bbw
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    f["bbw"] = ((4*sd) / mid * 100)
    # trend_age: EMA20/60/200 对齐状态持续时长
    e20, e60, e200 = c.ewm(span=20).mean(), c.ewm(span=60).mean(), c.ewm(span=200).mean()
    up = (e20 > e60) & (e60 > e200)
    dn = (e20 < e60) & (e60 < e200)
    state = np.where(up, 1, np.where(dn, -1, 0))
    f["aligned"] = state != 0
    grp = pd.Series(state, index=df.index).ne(pd.Series(state, index=df.index).shift()).cumsum()
    f["trend_age"] = grp.groupby(grp).cumcount() + 1
    f.loc[~f["aligned"], "trend_age"] = 0
    f["trend_age"] = f["trend_age"].clip(upper=1440)
    # 与日线方向一致
    eday = c.ewm(span=1440).mean()
    f["d_align"] = np.where(state == 1, (c > eday).astype(int),
                    np.where(state == -1, (c < eday).astype(int), 0))
    feat[sym] = f.astype("float32")

bcon = sqlite3.connect(BT)
trades = bcon.execute("select symbol,action,created_at,result_pct,status from ai_advice_track "
                      "where status in ('WIN','LOSS') order by created_at").fetchall()

rows = []
for sym, action, ts, pct, st in trades:
    f = feat.get(sym)
    if f is None:
        continue
    t = pd.Timestamp(ts)
    i = f.index.searchsorted(t, side="right") - 1
    if i < 400:
        continue
    r = f.iloc[i]
    rows.append((ts, ts < TRAIN_END, r["er60"], r["atr_pct"], r["bbw"],
                 r["trend_age"], r["d_align"], pct > 0, pct))
T = pd.DataFrame(rows, columns=["ts", "train", "er60", "atr_pct", "bbw",
                                "trend_age", "d_align", "win", "pct"])
print(f"join成功 {len(T)} / {len(trades)} 笔 (训练期 {int(T['train'].sum())} / 测试期 {int((~T['train']).sum())})")

# 月度特征均值 vs 月度盈亏
print("\n== 月度特征均值 (对照该月每笔均亏) ==")
T["month"] = T["ts"].str[:7]
g = T.groupby("month").agg(n=("pct", "size"), mean_pnl=("pct", "mean"),
                           wr=("win", "mean"), er60=("er60", "mean"),
                           atr=("atr_pct", "mean"), bbw=("bbw", "mean"),
                           age=("trend_age", "mean"), dalign=("d_align", "mean"))
print(g.round(4).to_string())

# 训练期分位线 -> 双期分桶
print("\n== 特征分桶: 训练期(2-5月)定分位线, 双期各报 [n/WR/均笔pnl] ==")
tr = T[T["train"]]
for col in ("er60", "atr_pct", "bbw", "trend_age", "d_align"):
    qs = tr[col].quantile([0.2, 0.4, 0.6, 0.8]).values
    edges = [-np.inf, *qs, np.inf]
    lab = ["Q1", "Q2", "Q3", "Q4", "Q5"] if col != "d_align" else ["Q1", "Q2", "Q3", "Q4", "Q5"]
    T["bucket"] = pd.cut(T[col], bins=edges, labels=lab[:len(edges)-1])
    print(f"\n-- {col} --")
    for is_train, name in ((True, "训练2-5月"), (False, "测试6-8月")):
        sub = T[T["train"] == is_train].groupby("bucket", observed=True).agg(
            n=("pct", "size"), wr=("win", "mean"), pnl=("pct", "mean"))
        line = f"  {name}: "
        for b, r in sub.iterrows():
            line += f"{b} n={int(r.n):>4} WR={r.wr*100:>4.1f}% {r.pnl:+.3f} | "
        print(line)
