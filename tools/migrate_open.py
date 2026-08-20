import sqlite3
db = sqlite3.connect("/mnt/nvme/quanforge/data/paper_trendrule_tp5.db")
sv = "v4.8.3-trendrule-paper-tp5R-risk1-gate0.32"
rows = [
    ("SNDKUSDT", "BUY", 1596.21, 1586.34, 1642.66, "2026-08-20 15:24:00", "2026-08-20 15:53:00"),
    ("ACEUSDT", "BUY", 0.281114, 0.275151, 0.310427, "2026-08-20 15:52:00", "2026-08-20 15:53:00"),
]
for sym, act, entry, sl, tp, created, entered in rows:
    db.execute(
        "insert into ai_advice_track(symbol,action,entry,stop_loss,take_profit,"
        "status,result_pct,note,sys_version,created_at,entered_at,settled_at,llm_ms) "
        "values(?,?,?,?,?,?,?,?,?,?,?,?,0)",
        (sym, act, entry, sl, tp, "OPEN", None, "v4.8.4迁移自在场持仓", sv, created, entered, None))
db.commit()
for r in db.execute("select id, symbol, status, entry from ai_advice_track where status='OPEN'"):
    print(r)
