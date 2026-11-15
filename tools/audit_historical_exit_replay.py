#!/usr/bin/env python3
"""Actual QF-S v5 entries and fetched Bybit OHLC, with controlled poll outages.

Exit-path experiment only: freeze regime at MIXED and bypass indicator warmup
(WARMUP=1); never generate entries. Historical trade parameters are unchanged.
Initial notional $200 and fee/slippage are explicit comparison assumptions.
Never opens live APIs, never writes either input database.
"""
import argparse
import calendar
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from unittest.mock import patch

from audit_paper_replay import load, HOUR


def epoch(value):
    return calendar.timegm(time.strptime(value, "%Y-%m-%d %H:%M:%S"))*1000


def hours(connection, symbol):
    groups = {}
    for b in connection.execute("select ts,open,high,low,close,volume from bars where symbol=? order by ts", (symbol,)):
        groups.setdefault(b[0]//HOUR*HOUR, []).append(b)
    result = {}
    for ts, rows in groups.items():
        if len(rows) == 60 and [r[0] for r in rows] == list(range(ts, ts+HOUR, 60000)):
            result[ts] = (ts, rows[0][1], max(r[2] for r in rows), min(r[3] for r in rows), rows[-1][4], sum(r[5] for r in rows))
    return result


def replay(trade, bars, baseline, stride):
    m = load(baseline)
    m.WARMUP = 1
    sym = trade["symbol"]
    entry, sl = trade["entry"], trade["stop_loss"]
    entry_ms = epoch(trade["created_at"])+HOUR
    initial = 200.
    observed_exit, first_stop, errors = None, None, []
    peak, max_dd = initial, 0.
    with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
        m.DB = str(Path(d)/"run.db")
        con = m.init_db()
        m.enter(con, sym, trade["action"], entry, abs(entry-sl)/m.SL_ATR_MULT, entry_ms)
        # Fixed exposure is an experiment assumption; legacy ledger never stored it.
        m.pos[sym]["notional"] = 200.
        # Also force old settlement arithmetic to the same fixed exposure, since this
        # experiment isolates exits rather than sizing (equity remains $200 pre-exit).
        risk = abs(entry-sl)/entry*100
        m.RISK_PCT = risk
        m.last_bar[sym] = entry_ms-HOUR
        m.last_state[sym] = "MIXED"
        for i, b in enumerate(bars):
            hit = b[3] <= sl if trade["action"] == "BUY" else b[2] >= sl
            if first_stop is None and hit:
                first_stop = b[0]+HOUR
            if i % stride != stride-1 and i != len(bars)-1:
                mark = m.equity
                if sym in m.pos:
                    mark += 200.*(b[4]-entry)/entry*(1 if trade["action"] == "BUY" else -1)
                peak = max(peak, mark)
                max_dd = max(max_dd, (peak-mark)/peak*100.)
                continue
            response = bars[:i+1]
            with patch.object(m, "rest_klines", return_value=response), patch.object(m, "classify", return_value="MIXED"):
                try:
                    m.tick(con, sym, b[0]+HOUR)
                except (RuntimeError, ValueError) as e:
                    errors.append(str(e))
            mark = m.equity
            if sym in m.pos:
                mark += 200.*(b[4]-entry)/entry*(1 if trade["action"] == "BUY" else -1)
            else:
                observed_exit = b[0]+HOUR
            peak = max(peak, mark)
            max_dd = max(max_dd, (peak-mark)/peak*100.)
            if sym not in m.pos:
                break
        row = con.execute("select status,result_pct,settled_at from ai_advice_track").fetchone()
        gross = (row[1] or 0)*2
        closed = row[0] != "OPEN"
        result = dict(trade_id=trade["id"], symbol=sym, action=trade["action"],
                      version="before" if baseline else "after", poll_stride_hours=stride,
                      actual_complete_hours=len(bars), entries=1, exits=int(closed),
                      gross_pnl_usd=round(gross, 6), fees_usd=0.22 if closed else 0.,
                      assumed_slippage_usd=0.08 if closed else 0., funding_usd=None,
                      net_realized_under_assumed_costs_usd=round(gross-(0.30 if closed else 0), 6),
                      gross_marked_max_drawdown_pct=round(max_dd, 6),
                      observed_exit_delay_after_first_stop_hour_close_min=(observed_exit-first_stop)/60000
                          if first_stop is not None and observed_exit is not None else None,
                      anomalous_missing_stop_exit=int(first_stop is not None and not closed),
                      open_at_end=int(not closed), rejected_polls=len(errors))
        con.close()
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", required=True, type=Path)
    p.add_argument("--out", type=Path, default=Path("docs/audit-20261112/historical-exit-replay.json"))
    a = p.parse_args()
    ledger = a.snapshot/"paper_v5mech.db"
    histories = sorted(a.snapshot.glob("history*.sqlite"))
    if not histories:
        raise RuntimeError("no captured historical OHLC databases")
    c = sqlite3.connect(ledger.resolve().as_uri()+"?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    trades = [dict(r) for r in c.execute("select * from ai_advice_track where status in ('WIN','LOSS') order by id")]
    c.close()
    h = sqlite3.connect(":memory:")
    h.execute("create table bars(symbol text,ts integer,open real,high real,low real,close real,volume real,turnover real,primary key(symbol,ts))")
    for source in histories:
        with sqlite3.connect(source.resolve().as_uri()+"?mode=ro", uri=True) as source_db:
            h.executemany("insert or ignore into bars values(?,?,?,?,?,?,?,?)", source_db.execute("select symbol,ts,open,high,low,close,volume,turnover from bars"))
    cache = {s: hours(h, s) for s in {r["symbol"] for r in trades}}
    h.close()
    output, skipped = [], []
    for trade in trades:
        entry_ms = epoch(trade["created_at"])+HOUR
        available = cache[trade["symbol"]]
        selected = []
        for n in range(25):
            b = available.get(entry_ms+n*HOUR)
            if b is None:
                break
            selected.append(b)
        if not selected:
            skipped.append(dict(trade_id=trade["id"], reason="no contiguous complete hour after entry"))
            continue
        for stride in (1, 4):
            for old in (True, False):
                output.append(replay(trade, selected, old, stride))
    data = dict(kind="real historical OHLC + actual ledger entry/SL + synthetic poll outage; exit-path experiment, not strategy backtest",
                baseline_commit="23b1a9b", assumptions=dict(initial_equity_usd=200, entry_notional_usd=200,
                    roundtrip_fee_usd=0.22, roundtrip_slippage_usd=0.08, funding="unknown",
                    signal_regime="frozen MIXED; WARMUP=1 for isolated exit seam", max_hold_hours=25,
                    entry_clock="legacy created_at is signal-bar OPEN; assumed execution at its CLOSE (+1h)"),
                inputs_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [ledger]+histories},
                original_trade_count=len(trades), eligible_trade_count=len(output)//4,
                skipped=skipped, results=output)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(dict(eligible_trades=data["eligible_trade_count"], skipped=len(skipped), runs=len(output))))
    for stride in (1, 4):
        for version in ("before", "after"):
            xs = [x for x in output if x["poll_stride_hours"]==stride and x["version"]==version]
            print(stride, version, "exits",sum(x["exits"] for x in xs), "gross",round(sum(x["gross_pnl_usd"] for x in xs),6), "missing_stop",sum(x["anomalous_missing_stop_exit"] for x in xs))


if __name__ == "__main__":
    main()
