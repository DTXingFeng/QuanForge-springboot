#!/usr/bin/env python3
"""仓位研究: alts-only + 门槛 5R 账本, 时序重建权益曲线
有效杠杆 L = margin% × 100x. 现行生产 5%(x100)=5x.
变体: L=2.5 / 5 / 10. 指标: 终值/月化/最大回撤/最低点/最长连亏/负月数"""
import sqlite3
import numpy as np
import pandas as pd

kcon = sqlite3.connect("/mnt/nvme/quanforge/data/quanforge.db")
ALTS = ["ACEUSDT", "ZECUSDT", "SNDKUSDT"]
atr_s = {}
for sym in ALTS:
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
                   "where status in ('WIN','LOSS') order by created_at").fetchall()
trades = []
for sym, ts, pct in rows:
    if sym not in ALTS:
        continue
    s = atr_s[sym]
    t = pd.Timestamp(ts)
    i = s.index.searchsorted(t, side="right") - 1
    if i < 400 or float(s.iloc[i]) < 0.32:
        continue
    trades.append((ts, pct))
print(f"门槛内 alts 5R: n={len(trades)} 笔 (6.5个月)\n")

E0 = 200.0
for L in (2.5, 5.0, 10.0):
    eq = E0
    peak, mdd, trough = eq, 0.0, eq
    streak, worst_streak, cur_streak = 0, 0, 0
    monthly = {}
    for ts, pct in trades:
        eq *= (1 + pct / 100 * L)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
        trough = min(trough, eq)
        if pct < 0:
            cur_streak += 1
            worst_streak = max(worst_streak, cur_streak)
        else:
            cur_streak = 0
        monthly[ts[:7]] = monthly.get(ts[:7], 1.0) * (1 + pct / 100 * L)
    neg_months = sum(1 for v in monthly.values() if v < 1)
    months = len(monthly)
    print(f"L={L:>4.1f}x: 终值 {eq:8.1f} ({(eq/E0-1)*100:+8.1f}%, 月化~{((eq/E0)**(1/months)-1)*100:+5.1f}%) "
          f"最大回撤 {mdd*100:5.1f}%  最低点 {trough:6.1f}  最长连亏 {worst_streak}  "
          f"负月 {neg_months}/{months}")

# 连亏分布 + 单笔最大亏损的权益冲击
pcts = [p for _, p in trades]
losses = sorted([p for p in pcts if p < 0])
print(f"\n单笔亏损分布: p50={losses[len(losses)//2]:.2f}% p95={losses[int(len(losses)*0.05)]:.2f}% "
      f"最差={losses[0]:.2f}%  -> L=5x 下权益冲击 {losses[0]*5:.1f}%")
win_streaks = 0
cur = 0
for _, p in trades:
    cur = cur + 1 if p > 0 else 0
    win_streaks = max(win_streaks, cur)
print(f"(对照) 最长连胜 {win_streaks} — 赔率形状: 长连亏+稀疏大赢, 权益曲线必然锯齿")

# ---- 风险平价仓位: 每笔风险 = equity × RISK%, 名义 = 风险额 / SL距离% ----
# SL距离 = 1.2×ATR%(入场时), 已有 atr. 权益冲击 = pnl%/sl% × RISK%
print("\n== 风险平价: RISK ∈ {0.5, 1, 2}% 每笔 ==")
trades_r = []
for sym, ts, pct in rows:
    if sym not in ALTS:
        continue
    s = atr_s[sym]
    t = pd.Timestamp(ts)
    i = s.index.searchsorted(t, side="right") - 1
    if i < 400:
        continue
    a = float(s.iloc[i])
    if a < 0.32:
        continue
    trades_r.append((ts, pct, a * 1.2))
for RISK in (0.5, 1.0, 2.0):
    eq, peak, mdd, trough = E0, E0, 0.0, E0
    monthly = {}
    for ts, pct, slp in trades_r:
        eq *= (1 + pct / slp * RISK / 100)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
        trough = min(trough, eq)
        monthly[ts[:7]] = monthly.get(ts[:7], 1.0) * (1 + pct / slp * RISK / 100)
    neg = sum(1 for v in monthly.values() if v < 1)
    print(f"RISK={RISK:.1f}%: 终值 {eq:8.1f} ({(eq/E0-1)*100:+8.1f}%) 最大回撤 {mdd*100:5.1f}% "
          f"最低点 {trough:6.1f} 负月 {neg}/{len(monthly)}")
