import sqlite3
print("== 前向首两笔记账审计: 模拟盘实记 vs 引擎公式 ==")
for label, db, tp_r in [("3R", "/mnt/nvme/quanforge/data/paper_trendrule.db", 3.0),
                        ("5R", "/mnt/nvme/quanforge/data/paper_trendrule_tp5.db", 5.0)]:
    con = sqlite3.connect(db)
    rows = con.execute(
        "select symbol, action, entry, stop_loss, take_profit, status, result_pct, settled_at "
        "from ai_advice_track where status in ('WIN','LOSS') order by settled_at").fetchall()
    eq = 200.0
    for sym, act, entry, sl, tp, st, pct, ts in rows:
        sign = -1 if act == "SELL" else 1
        move_check = sign * (entry - tp) / entry * 100 / tp_r if st == "WIN" else None
        risk0 = abs(tp - entry) / entry * 100 / tp_r
        base = min(eq * 1.0 / risk0, eq * 5.0) if risk0 > 0.01 else eq * 5.0
        impact = base * pct / 100.0
        eq += impact
        ok = "OK" if st == "WIN" and abs(abs(pct) - abs(entry - tp) / entry * 100) < 0.02 else \
             ("OK" if st == "LOSS" and abs(abs(pct) - abs(entry - sl) / entry * 100) < 0.02 else "CHECK")
        print(f"{label} {st} {act} {sym}: pct={pct:+.3f}% risk0={risk0:.4f}% "
              f"base={base:.1f} impact={impact:+.2f} eq={eq:.2f} TP/SL吻合={ok}")
