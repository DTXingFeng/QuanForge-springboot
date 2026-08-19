#!/usr/bin/env python3
"""补充: L0已结算单识别(llm_ms=1) + 权益曲线最大回撤"""
import sqlite3

DBS = {"full": "/mnt/nvme/quanforge/data/backtest.db",
       "l0":   "/mnt/nvme/quanforge/data/backtest_l0.db",
       "lat":  "/mnt/nvme/quanforge/data/backtest_lat.db"}
NOTIONAL = 1000.0

print("== l0 臂内: L0已结算单 (llm_ms<=10) vs LLM单 ==")
con = sqlite3.connect(DBS["l0"])
for label, cond in [("L0规则单", "llm_ms<=10"), ("LLM单", "llm_ms>10")]:
    rs = con.execute(f"select result_pct,status from ai_advice_track "
                     f"where status in ('WIN','LOSS') and {cond}").fetchall()
    if not rs: print(label, "n=0"); continue
    w = [r for r in rs if r[1] == "WIN"]; gp = sum(r[0] for r in w)
    l = [r for r in rs if r[1] == "LOSS"]; gl = abs(sum(r[0] for r in l))
    print(f"{label:<8} n={len(rs):>4} W/L={len(w)}/{len(l)} WR={len(w)/len(rs)*100:.1f}% "
          f"PF={gp/gl if gl else 999:.2f} 累计={sum(r[0] for r in rs):+.1f}%")

print("\n== 权益曲线最大回撤 (每臂整体时序, $1200 基线=6段x$200) ==")
for name, db in DBS.items():
    con = sqlite3.connect(db)
    rows = con.execute("select created_at,result_pct from ai_advice_track "
                       "where status in ('WIN','LOSS') order by created_at").fetchall()
    eq, peak, mdd = 1200.0, 1200.0, 0.0
    for _, pct in rows:
        eq += NOTIONAL * pct / 100
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    print(f"{name:<6} 终值=${eq:.0f} ({(eq/1200-1)*100:+.1f}%)  最大回撤=${mdd:.0f} ({mdd/1200*100:.1f}%)")

print("\n== lat臂弃单后1小时内行情 (被弃单方向是否本来会赚: 逆势单?) ==")
con = sqlite3.connect(DBS["lat"])
exp = con.execute("select symbol,action,created_at from ai_advice_track where status='EXPIRED' "
                  "order by created_at").fetchall()
import glob
# 用 full 臂同触发对比: full 同时刻成交的单 -> 看这些触发在零延迟下的表现
full = sqlite3.connect(DBS["full"])
full_map = {(r[0], r[1]): r[2] for r in full.execute(
    "select symbol,action,created_at,result_pct from ai_advice_track where status in ('WIN','LOSS')")}
matched, w, tot = 0, 0, 0.0
for sym, act, ts in exp:
    key = (sym, act)
    # 找 full 臂同币种同方向、5分钟内的结算单
    r = full.execute("select result_pct from ai_advice_track where status in('WIN','LOSS') "
                     "and symbol=? and action=? and abs(julianday(created_at)-julianday(?))<0.0035",
                     (sym, act, ts)).fetchone()
    if r:
        matched += 1; tot += r[0]
        if r[0] > 0: w += 1
print(f"弃单在full臂有对应成交: {matched}/{len(exp)}, 其中盈利 {w} ({w/matched*100 if matched else 0:.0f}%), "
      f"对应累计 {tot:+.1f}% -> 这些'跑掉的单'合计本可赚/亏 ${tot*10:.0f}")

print("\n== lat臂 成交单 vs full臂 全部单 的PF差异解释 ==")
for name in ("full", "lat"):
    con = sqlite3.connect(DBS[name])
    rs = con.execute("select result_pct,status from ai_advice_track where status in ('WIN','LOSS')").fetchall()
    avg_w = sum(r[0] for r in rs if r[1]=="WIN")/max(1,len([r for r in rs if r[1]=="WIN"]))
    avg_l = sum(r[0] for r in rs if r[1]=="LOSS")/max(1,len([r for r in rs if r[1]=="LOSS"]))
    print(f"{name:<5} 平均盈利单 {avg_w:+.2f}%  平均亏损单 {avg_l:+.2f}%")
