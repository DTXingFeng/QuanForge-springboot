#!/usr/bin/env python3
"""Deterministic offline engineering replay; no strategy optimisation or live IO.

Pairs use identical fixture bars, initial position, parameters, and external costs.
Gross engine results and marked equity are separate from the assumed-cost account.
Baseline is the pinned pre-audit Git source, not an older QuantForge project.
"""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOUR = 3600000
START = 1700002800000
BASELINE = "23b1a9b"


def load(baseline):
    if baseline:
        source = subprocess.check_output(["git", "show", BASELINE + ":tools/paper_v5mech.py"], cwd=ROOT).decode("utf-8")
        module = types.ModuleType("v5_baseline")
        exec(compile(source, "git:" + BASELINE, "exec"), module.__dict__)
        return module
    spec = importlib.util.spec_from_file_location("v5_fixed", ROOT / "tools/paper_v5mech.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(scenario, baseline, fee_rate, slippage_rate):
    m = load(baseline)
    sym = "ACEUSDT"
    bars = [(START+i*HOUR, 100., 100.5, 99.5, 100., 1.) for i in range(220)]
    direction = "SELL" if scenario == "fast_down" else "BUY"
    for n in range(1, 27):
        price = 100. + (0.5*n if scenario == "fast_up" else -0.5*n if scenario == "fast_down" else 0.)
        if scenario == "extreme_gap":
            price = 95.
        bars.append((START+(219+n)*HOUR, price, price+0.5, price-0.5, price, 1.))
    if scenario in ("network_outage", "restart", "api_timeout"):
        bars[220] = (bars[220][0], 100., 100.5, 98., 100., 1.)
    eq_path = [200.]
    errors = []
    first_recovery_open = None
    observed_exit_at = None
    with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
        m.DB = str(Path(d) / "paper.db")
        con = m.init_db()
        m.enter(con, sym, direction, 100., 1./1.2, START+220*HOUR)
        m.last_bar[sym] = bars[219][0]
        m.last_state[sym] = "MIXED"
        if hasattr(m, "save_runtime"):
            m.save_runtime(con, sym)
        con.commit()
        if scenario == "restart":
            m.pos.clear(); m.last_bar.clear(); m.last_state.clear()
            m.restore(con)
        polls = list(range(220, len(bars)))
        if scenario in ("network_outage", "restart", "api_timeout"):
            polls = polls[3:]
        if scenario == "api_timeout":
            with patch.object(m, "rest_klines", side_effect=TimeoutError("fixture timeout")):
                try:
                    m.tick(con, sym, bars[220][0]+HOUR)
                except TimeoutError:
                    errors.append("fixture timeout")
        for idx in polls:
            response = bars[:idx+1]
            if scenario == "missing_hour":
                response = [b for b in response if b[0] != bars[220][0]]
            if scenario == "out_of_order":
                response = list(reversed(response))
            if scenario == "duplicate_response":
                response = response + [response[-1]]
            with patch.object(m, "rest_klines", return_value=response), patch.object(m, "classify", return_value="MIXED"):
                try:
                    m.tick(con, sym, bars[idx][0]+HOUR)
                    if scenario == "duplicate_response":
                        m.tick(con, sym, bars[idx][0]+HOUR)
                except (RuntimeError, ValueError) as error:
                    errors.append(str(error))
            if first_recovery_open is None:
                first_recovery_open = sym in m.pos
            if observed_exit_at is None and sym not in m.pos:
                observed_exit_at = bars[idx][0]+HOUR
            # P&L comparison includes open exposure at current close, so missing
            # exits cannot masquerade as risk-free cash. Entry notional is $200.
            mark = m.equity
            if sym in m.pos:
                mark += 200. * (bars[idx][4]-100.)/100. * (1 if direction == "BUY" else -1)
            eq_path.append(mark)
        rows = con.execute("select status,result_pct,entered_at,settled_at from ai_advice_track").fetchall()
        settled = [r for r in rows if r[0] in ("WIN", "LOSS")]
        gross = sum((r[1] or 0.)*2 for r in settled)  # fixed $200 entry exposure
        fees = len(settled)*200.*2*fee_rate
        slippage = len(settled)*200.*2*slippage_rate
        peak, max_dd = 200., 0.
        for mark in eq_path:
            peak = max(peak, mark)
            max_dd = max(max_dd, (peak-mark)/peak*100)
        delay = None
        if settled and scenario in ("extreme_gap", "network_outage", "restart", "api_timeout"):
            import calendar, time
            reported = calendar.timegm(time.strptime(settled[0][3], "%Y-%m-%d %H:%M:%S"))*1000
            # Old ledger timestamps are bar OPEN, patched ledger timestamps are CLOSE.
            close_clock = reported + (HOUR if baseline else 0)
            delay = (close_clock - (bars[220][0]+HOUR))/60000
        con.close()
    return dict(scenario=scenario, version="before" if baseline else "after",
                entries=len(rows), exits=len(settled), gross_pnl_usd=round(gross, 6),
                fees_usd=round(fees, 6), slippage_usd=round(slippage, 6), funding_usd=None,
                net_pnl_under_assumed_costs_usd=round(gross-fees-slippage, 6),
                gross_marked_max_drawdown_pct=round(max_dd, 6),
                ledger_exit_bar_delay_after_stop_bar_close_min=delay,
                observed_exit_delay_after_stop_bar_close_min=(observed_exit_at-(bars[220][0]+HOUR))/60000
                    if observed_exit_at is not None and scenario in ("extreme_gap", "network_outage", "restart", "api_timeout") else None,
                missed_stop_on_first_recovery=int(scenario in ("network_outage", "restart", "api_timeout") and first_recovery_open),
                safe_data_rejections_or_api_errors=len(errors), open_at_end=int(not settled))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=ROOT/"docs/audit-20261112/python-replay.json")
    p.add_argument("--fee-rate", type=float, default=0.00055, help="explicit synthetic assumption per side, not account evidence")
    p.add_argument("--slippage-rate", type=float, default=0.0002)
    a = p.parse_args()
    scenarios = ["normal", "fast_up", "fast_down", "extreme_gap", "network_outage", "restart", "api_timeout", "duplicate_response", "missing_hour", "out_of_order"]
    output = dict(kind="synthetic engineering replay, not historical profitability", baseline_commit=BASELINE,
                  assumptions=dict(equity_usd=200, entry_notional_usd=200, fee_rate_per_side=a.fee_rate,
                                   slippage_rate_per_side=a.slippage_rate, funding="unknown; not imputed"),
                  results=[run(s, old, a.fee_rate, a.slippage_rate) for s in scenarios for old in (True, False)])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
