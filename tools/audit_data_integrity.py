#!/usr/bin/env python3
"""Read-only, standard-library evidence audit. Never opens a network connection."""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sqlite3


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat()


def audit(path, history=None):
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    out = {"database_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
           "timestamp_note": "open_time is SQLite JDBC integer; interpreted as Unix milliseconds UTC. Legacy LocalDateTime encoding can carry timezone ambiguity; months of staleness cannot be explained by an 8h offset.",
           "integrity_check": con.execute("PRAGMA quick_check").fetchone()[0], "symbols": {}}
    for (symbol,) in con.execute("SELECT DISTINCT symbol FROM kline_1m ORDER BY symbol"):
        rows = con.execute("SELECT open_time,open,high,low,close,volume FROM kline_1m WHERE symbol=? ORDER BY open_time", (symbol,)).fetchall()
        gaps = []
        invalid = 0
        for i, row in enumerate(rows):
            ts, o, h, lo, c, v = row
            invalid += int(not all(math.isfinite(x) for x in (o,h,lo,c,v)) or min(o,h,lo,c) <= 0 or v < 0 or h < max(o,c,lo) or lo > min(o,c,h))
            if i and ts - rows[i-1][0] != 60_000:
                gaps.append({"after_ms": rows[i-1][0], "before_ms": ts, "missing_minutes": (ts-rows[i-1][0]) // 60_000 - 1})
        out["symbols"][symbol] = {"rows": len(rows), "first_ms": rows[0][0], "last_ms": rows[-1][0],
            "first_utc": iso(rows[0][0]), "last_utc": iso(rows[-1][0]),
            "misaligned_timestamps": sum(r[0] % 60_000 != 0 for r in rows),
            "duplicate_timestamps": len(rows) - len({r[0] for r in rows}),
            "invalid_ohlcv": invalid, "gap_count": len(gaps),
            "missing_minutes": sum(g["missing_minutes"] for g in gaps), "gaps": gaps}
    out["advice_columns"] = [r[1] for r in con.execute("PRAGMA table_info(ai_advice_track)")]
    out["advice_created_range"] = list(con.execute("SELECT min(created_at),max(created_at),count(*) FROM ai_advice_track").fetchone())
    out["advice_entry_time_inside_archived_kline_range"] = con.execute(
        "SELECT count(*) FROM ai_advice_track a JOIN "
        "(SELECT symbol,min(open_time) mn,max(open_time) mx FROM kline_1m GROUP BY symbol) k USING(symbol) "
        "WHERE a.created_at BETWEEN k.mn AND k.mx+60000").fetchone()[0]
    out["alert_created_range"] = list(con.execute("SELECT min(created_at),max(created_at),count(*) FROM ai_alert").fetchone())
    if history:
        con.execute("ATTACH DATABASE ? AS replay", (history.resolve().as_uri() + "?mode=ro",))
        joined = "FROM kline_1m k JOIN replay.bars b ON k.symbol=b.symbol AND k.open_time=b.ts"
        out["public_replay_crosscheck"] = {
            "history_sha256": hashlib.sha256(history.read_bytes()).hexdigest(),
            "overlapping_bars": con.execute("SELECT count(*) " + joined).fetchone()[0],
            "differences": [dict(zip(("symbol", "ts", "stored_open", "public_open", "stored_high", "public_high", "stored_low", "public_low", "stored_close", "public_close", "stored_volume", "public_volume"), row))
                for row in con.execute("SELECT k.symbol,k.open_time,k.open,b.open,k.high,b.high,k.low,b.low,k.close,b.close,k.volume,b.volume " + joined +
                    " WHERE abs(k.close-b.close)>1e-9 OR abs(k.high-b.high)>1e-9 OR abs(k.low-b.low)>1e-9 ORDER BY k.symbol,k.open_time")],
            "note": "Independent fresh public REST history; price mismatches do not alone prove a particular trade's loss cause."}
    con.close()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("database", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--history", type=Path, help="Optional independently recaptured public history.sqlite (bars table)")
    args = ap.parse_args()
    result = json.dumps(audit(args.database, args.history), ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(result + "\n", encoding="utf-8")
    else:
        print(result)
