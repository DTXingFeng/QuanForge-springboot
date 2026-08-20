#!/usr/bin/env python3
"""延迟税终审: full(零延迟) vs live(生产:判完偏离>0.15%挂限价) vs lat2(判完追价成交)"""
import sqlite3

ARMS = {"full": "/mnt/nvme/quanforge/data/backtest.db",
        "live": None, "lat2": None}  # live/lat2 从seg合并
import subprocess
for a in ("live", "lat2"):
    out = f"/mnt/nvme/quanforge/data/backtest_{a}.db"
    subprocess.run(["python3", "/mnt/nvme/quanforge/tools/merge_backtest.py",
                    a, "6", out], capture_output=True)
    ARMS[a] = out

for name, db in ARMS.items():
    con = sqlite3.connect(db)
    rows = con.execute("select status,result_pct,note from ai_advice_track").fetchall()
    st = [r for r in rows if r[0] in ("WIN", "LOSS")]
    w = [r for r in st if r[0] == "WIN"]
    l = [r for r in st if r[0] == "LOSS"]
    gp = sum(r[1] for r in w); gl = abs(sum(r[1] for r in l))
    exp = sum(1 for r in rows if r[0] == "EXPIRED")
    blk = sum(1 for r in rows if r[0] == "BLOCKED")
    print(f"{name:<5} 成交={len(st):>4} WR={len(w)/len(st)*100:>5.1f}% PF={gp/gl:>5.2f} "
          f"累计={sum(r[1] for r in st):>+7.1f}%  EXPIRED={exp:>4} BLOCKED={blk:>4}")
    # 弃单原因分解
    if exp:
        from collections import Counter
        c = Counter((r[2] or "")[:18] for r in rows if r[0] == "EXPIRED")
        print("      弃单原因:", dict(c.most_common(4)))
