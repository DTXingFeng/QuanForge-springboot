import sqlite3
for f in ["/mnt/nvme/quanforge/data/backtest_final3.db", "/mnt/nvme/quanforge/data/backtest_final5.db"]:
    db = sqlite3.connect(f)
    cols = [r[1] for r in db.execute("pragma table_info(ai_advice_track)")]
    print(f.split("/")[-1], "cols:", cols)
    for st, n in db.execute("select status, count(*) from ai_advice_track group by status"):
        print("   ", st, n)
    print("   note dist:")
    for note, n in db.execute("select note, count(*) from ai_advice_track group by note order by 2 desc limit 10"):
        print("     ", repr(note), n)
    r = db.execute("select min(settled_at), max(settled_at) from ai_advice_track where status in ('WIN','LOSS')").fetchone()
    print("   settled range:", r)
    # result_pct 分布
    for st in ("WIN", "LOSS"):
        row = db.execute("select avg(result_pct), median_dummy from (select result_pct, row_number() over (order by result_pct) rn, count(*) over () n from ai_advice_track where status=?) where rn=(n+1)/2", (st,)).fetchone()
        print(f"   {st} avg={row[0]:+.4f}% median={row[1]:+.4f}%")
