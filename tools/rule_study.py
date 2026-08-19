#!/usr/bin/env python3
"""6个月免LLM方向研究: 同触发同规则, 方向=15m+1h趋势顺势, 多空分开统计.
回答: "山寨顺势空单系统性差于顺势多单"是持久规律还是单月噪音?
规则尽量贴 backtest.py: 触发/冷却/SL=1.2ATR(主币钳2.2%)/TP=2R/TTL; 无LLM无熔断."""
import sqlite3
import numpy as np
import pandas as pd

PROD_DB = "/mnt/nvme/quanforge/data/quanforge.db"
MAJORS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
SHOCK_1M, IMPULSE_5M, COOLDOWN_S = 0.35, 0.80, 300
SCAN_PCT15M, SCAN_RSI_X = 0.5, 25.0
CLAMP_MAJORS = 2.2
TTL_ALTS, TTL_MAJORS = 120, 240
SL_MULT = 1.2
import sys
VARIANT = sys.argv[1] if len(sys.argv) > 1 else "base"
# base   = 原版(零滑点, 触发方向不限)
# slip   = 市价滑点0.05% (贴近生产成交)
# dirf   = 触发方向必须与趋势一致(1m/5m冲击方向=趋势方向才进)
# dirslip= dirf + slip
SLIP = 0.0005 if VARIANT in ("slip", "dirslip") else 0.0
DIRF = VARIANT in ("dirf", "dirslip")

def rsi(s, period=14):
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    return (100 - 100/(1 + g/l.replace(0, np.nan))).fillna(50)

def atr(df, period=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"]-df["low"], (df["high"]-pc).abs(),
                    (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

con = sqlite3.connect(PROD_DB)
res = {}   # (sym, month, action) -> [n, wins, pnl_sum]
for sym in ("ACEUSDT", "SNDKUSDT", "ZECUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"):
    df = pd.read_sql_query(
        f"select open_time,open,high,low,close from kline_1m where symbol='{sym}' "
        f"and open_time>=1771000000000 order by open_time", con)
    if len(df) < 20000:
        print(f"[skip] {sym} 数据不足 {len(df)}")
        continue
    df.index = pd.to_datetime(df["open_time"], unit="ms")
    df = df[["open", "high", "low", "close"]]
    c = df["close"]
    ema20 = c.ewm(span=20).mean(); ema60 = c.ewm(span=60).mean(); ema200 = c.ewm(span=200).mean()
    rs = rsi(c); at = atr(df)
    pct1m = c.pct_change(); pct5m = c.pct_change(5); pct15m = c.pct_change(15)
    pos = {}; last_trig = {}
    for i in range(500, len(df)):
        i_ts = df.index[i]
        # ---- 持仓结算 ----
        if sym in pos:
            p = pos[sym]
            bar = df.iloc[i]
            buy = p["action"] == "BUY"
            hit_sl = bar["low"] <= p["sl"] if buy else bar["high"] >= p["sl"]
            hit_tp = bar["high"] >= p["tp"] if buy else bar["low"] <= p["tp"]
            if hit_sl and hit_tp:
                pct = (p["sl"] - p["entry"]) / p["entry"] * (100 if buy else -100)  # 同根双触保守判损
                key = (sym, str(i_ts)[:7], p["action"]); res.setdefault(key, [0,0,0.0])
                res[key][0] += 1; res[key][2] += pct; pos.pop(sym); continue
            if hit_sl:
                pct = (p["sl"] - p["entry"]) / p["entry"] * (100 if buy else -100)
                key = (sym, str(i_ts)[:7], p["action"]); res.setdefault(key, [0,0,0.0])
                res[key][0] += 1; res[key][2] += pct; pos.pop(sym); continue
            if hit_tp:
                pct = (p["tp"] - p["entry"]) / p["entry"] * (100 if buy else -100)
                key = (sym, str(i_ts)[:7], p["action"]); res.setdefault(key, [0,0,0.0])
                res[key][0] += 1; res[key][1] += 1; res[key][2] += pct; pos.pop(sym); continue
            if (i_ts - p["ts"]).total_seconds() / 60 > (TTL_MAJORS if sym in MAJORS else TTL_ALTS):
                pct = (c.iloc[i] - p["entry"]) / p["entry"] * (100 if buy else -100)
                key = (sym, str(i_ts)[:7], p["action"]); res.setdefault(key, [0,0,0.0])
                res[key][0] += 1; res[key][1] += (pct > 0); res[key][2] += pct; pos.pop(sym); continue
            continue
        # ---- 触发 ----
        if (i_ts.value - last_trig.get(sym, 0)) / 1e9 < COOLDOWN_S:
            continue
        r = rs.iloc[i]
        p1, p5, p15 = pct1m.iloc[i]*100, pct5m.iloc[i]*100, pct15m.iloc[i]*100
        trig = abs(p1) >= SHOCK_1M or abs(p5) >= IMPULSE_5M or \
               (i_ts.minute % 30 == 0 and (abs(p15) >= SCAN_PCT15M or r <= SCAN_RSI_X or r >= 100-SCAN_RSI_X))
        if not trig:
            continue
        last_trig[sym] = i_ts.value
        t15 = "UP" if ema20.iloc[i] > ema60.iloc[i] else "DOWN"
        t1h = "UP" if ema60.iloc[i] > ema200.iloc[i] else "DOWN"
        if t15 == t1h:
            action = "BUY" if t15 == "UP" else "SELL"
            if DIRF:
                # 触发冲击方向须与趋势一致: 上涨急动只做多, 下跌急动只做空
                shock_dir = "UP" if p1 >= 0 else "DOWN"
                if shock_dir != t15:
                    continue
            px = c.iloc[i]
            px = px * (1 + SLIP) if action == "BUY" else px * (1 - SLIP)
            sl_d = at.iloc[i] * SL_MULT
            if sl_d <= 0 or sl_d / px * 100 > 20:
                continue
            sl = px - sl_d if action == "BUY" else px + sl_d
            if sym in MAJORS and sl_d / px * 100 > CLAMP_MAJORS:
                sl = px - px*CLAMP_MAJORS/100 if action == "BUY" else px + px*CLAMP_MAJORS/100
            tp = px + 2*(px - sl) if action == "BUY" else px - 2*(sl - px)
            pos[sym] = {"action": action, "entry": px, "sl": sl, "tp": tp, "ts": i_ts}

print(f"\n[VARIANT={VARIANT}] {'币种':<9}{'月份':<9}{'BUY n/WR/累计%':>24}{'SELL n/WR/累计%':>24}")
months = sorted({k[1] for k in res})
for sym in ("ACEUSDT", "SNDKUSDT", "ZECUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"):
    for m in months:
        b = res.get((sym, m, "BUY")); s = res.get((sym, m, "SELL"))
        if not b and not s:
            continue
        def fmt(x):
            if not x: return f"{'--':>24}"
            return f"{x[0]:>7} {x[1]/x[0]*100:>5.0f}% {x[2]:>+8.1f}"
        print(f"{sym:<9}{m:<9}{fmt(b):>24}{fmt(s):>24}")

print(f"\n== [VARIANT={VARIANT}] 汇总: 各币种 顺势BUY vs 顺势SELL 全期 ==")
for sym in ("ACEUSDT", "SNDKUSDT", "ZECUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"):
    for a in ("BUY", "SELL"):
        rows = [v for (s, m, ac), v in res.items() if s == sym and ac == a]
        if rows:
            n = sum(r[0] for r in rows); w = sum(r[1] for r in rows); p = sum(r[2] for r in rows)
            print(f"{sym:<9} {a:<4} n={n:>5} WR={w/n*100:>4.0f}% 累计={p:>+8.1f}%")
