#!/usr/bin/env python3
"""3R vs 5R 参考回测风险画像 v3 — 精确重建:
risk0_init = |tp-entry|/entry/TP_R (TP在策略中从不移动, 保本移动后sl==entry仍可反推)
base = min(eq*RISK_PCT/risk0, eq*5), impact = base*pct/100 — 与引擎settle逐行同款.
交叉校验: 重建终值应≈引擎自报终值(3R 112.44 / 5R 555.58).
用法: python3 risk_profile.py"""
import sqlite3, datetime

E0 = 200.0
DBS = [
    ("3R", "/mnt/nvme/quanforge/data/backtest_final3.db", 3.0, 112.44),
    ("5R", "/mnt/nvme/quanforge/data/backtest_final5.db", 5.0, 555.58),
]

def profile(db, tp_r):
    con = sqlite3.connect(db)
    rows = con.execute(
        "select settled_at, entry, stop_loss, take_profit, status, result_pct "
        "from ai_advice_track "
        "where status in ('WIN','LOSS') and settled_at is not null "
        "order by settled_at").fetchall()
    eq = E0; peak = E0; mdd = 0.0; trough = E0
    wins = losses = 0; cur_w = cur_l = 0; max_w = max_l = 0
    daily_eq = {}
    for ts, entry, sl, tp, st, pct in rows:
        if entry and tp:
            risk0 = abs(tp - entry) / entry * 100 / tp_r
        else:
            risk0 = 0.0
        if risk0 <= 0.01:
            base = eq * 5.0
        else:
            base = min(eq * 1.0 / risk0, eq * 5.0)
        eq += base * pct / 100.0
        if eq <= 0:
            eq = 0.01
        peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak); trough = min(trough, eq)
        if pct > 0: wins += 1; cur_w += 1; cur_l = 0
        else: losses += 1; cur_l += 1; cur_w = 0
        max_w = max(max_w, cur_w); max_l = max(max_l, cur_l)
        daily_eq[ts[:10]] = eq
    n = len(rows)
    deq = sorted(daily_eq.items())
    dd_d = 0.0; pk = E0
    for d, v in deq:
        pk = max(pk, v); dd_d = max(dd_d, (pk - v) / pk)
    days_up = sum(1 for i in range(1, len(deq)) if deq[i][1] > deq[i-1][1])
    return {
        "n": n, "final": eq, "ret": (eq / E0 - 1) * 100,
        "mdd": mdd * 100, "mdd_daily": dd_d * 100, "trough": trough,
        "wr": wins / n * 100, "max_w": max_w, "max_l": max_l,
        "days": len(deq), "days_up": days_up,
    }

print("== 3R vs 5R 参考回测风险画像 v3 (引擎同款记账, $200起, RISK=1%) ==")
hdr = (f"{'':>4}{'n':>6}{'终值':>9}{'收益':>9}{'最大回撤':>9}{'按日回撤':>9}{'最低点':>9}"
       f"{'WR':>7}{'连胜':>5}{'连亏':>5}{'上涨日':>8}{'引擎自报':>10}{'偏差':>8}")
print(hdr)
for label, db, tp_r, reported in DBS:
    p = profile(db, tp_r)
    dev = (p["final"] - reported) / reported * 100
    print(f"{label:>4}{p['n']:>6}{p['final']:>9.1f}{p['ret']:>+8.1f}%{p['mdd']:>8.1f}%"
          f"{p['mdd_daily']:>8.1f}%{p['trough']:>9.1f}{p['wr']:>6.1f}%{p['max_w']:>5}"
          f"{p['max_l']:>5}{p['days_up']:>4}/{p['days']}{reported:>10.2f}{dev:>+7.2f}%")
print()
print("保本WR: 3R=25.0% 5R=16.7% -> 边际: 3R=-0.2pp(负), 5R=+2.7pp(正)")
