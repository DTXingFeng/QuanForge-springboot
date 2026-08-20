import sqlite3
db = sqlite3.connect("/mnt/nvme/quanforge/data/backtest_final5.db")
rows = db.execute(
    "select symbol, entry, stop_loss, take_profit, status, result_pct "
    "from ai_advice_track where status in ('WIN','LOSS') "
    "order by settled_at limit 12").fetchall()
eq = 200.0
for sym, entry, sl, tp, st, pct in rows:
    risk0 = abs(entry - sl) / entry * 100 if entry and sl else 0.0
    move = pct
    if risk0 < 0.05:
        base = 0.0
    else:
        base = min(eq * 1.0 / risk0, eq * 5.0)
    impact = base * move / 100.0
    eq += impact
    print(f"{sym:<10} {st:<4} entry={entry:<10} sl={sl:<10} tp={tp:<10} "
          f"risk0={risk0:6.3f}% pct={move:+8.3f}% base={base:8.1f} impact={impact:+8.2f} eq={eq:8.2f}")
print("final eq after 12:", eq)
# LOSS/WIN pct ranges
for st in ("WIN", "LOSS"):
    r = db.execute("select min(result_pct), max(result_pct), avg(result_pct), count(*) from ai_advice_track where status=?", (st,)).fetchone()
    print(st, "min/max/avg/n:", r)
# risk0 distribution across rows
r = db.execute("select avg(abs(entry-stop_loss)/entry*100), count(*) from ai_advice_track where status in ('WIN','LOSS') and entry is not null and stop_loss is not null").fetchone()
print("avg |entry-sl|%:", r)
