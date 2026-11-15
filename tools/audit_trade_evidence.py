"""Offline forensic inventory, not a backtest or causal profit attribution.

Only reads snapshot SQLite/JSON. Writes sanitized per-trade evidence and summaries.
Costs are reported as observed or unknown; never silently assumed zero.
"""
import argparse
import bisect
import collections
import csv
import datetime as dt
import hashlib
import json
import pathlib
import sqlite3
import statistics

SOURCES = ['quanforge.db', 'paper_trendrule.db', 'paper_trendrule_tp5.db',
           'paper_trendrule_tp5c.db', 'paper_v5mech.db']


def epoch(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return int(dt.datetime.fromisoformat(value).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def stamp(value):
    return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).isoformat() if value else ''


def readonly(path):
    c = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c


def load_exchange(path, stem, key):
    rows = {}
    for file in sorted(path.glob(stem + '-*.json')):
        data = json.loads(file.read_text())
        if data.get('retCode') != 0:
            continue
        for row in data.get('result', {}).get('list', []):
            rows[row[key]] = row
    return list(rows.values())


def excursions(bars, entered, settled, entry, buy):
    """Exclude partial entry/exit minutes: their full extrema were not held.

    This deliberately yields a conservative observed MFE/MAE, not tick precision.
    """
    first = ((entered + 59999) // 60000) * 60000
    last = settled // 60000 * 60000
    selected = [b for b in bars if first <= b[0] and b[0] + 60000 <= last]
    expected = max(0, (last - first) // 60000)
    good = [100 * ((b[2] if buy else entry) - (entry if buy else b[3])) / entry for b in selected]
    bad = [100 * ((b[3] if buy else entry) - (entry if buy else b[2])) / entry for b in selected]
    return selected, expected, max([0.0] + good), min([0.0] + bad)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--snapshot', type=pathlib.Path, required=True)
    ap.add_argument('--output', type=pathlib.Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    prices = collections.defaultdict(dict)
    for file in args.snapshot.glob('history*.sqlite'):
        with readonly(file) as c:
            for r in c.execute('select symbol,ts,open,high,low,close from bars'):
                prices[r[0]][r[1]] = (r[1], r[2], r[3], r[4], r[5])
    prices = {sym: sorted(rows.values()) for sym, rows in prices.items()}
    times = {sym: [b[0] for b in bars] for sym, bars in prices.items()}
    ex = args.snapshot / 'exchange'
    closes = load_exchange(ex, 'closed', 'orderId')
    executions = load_exchange(ex, 'execution', 'execId')
    orders = load_exchange(ex, 'orders', 'orderId')
    entry_exec = collections.defaultdict(list)
    for e in executions:
        entry_exec[e['orderId']].append(e)
    summary = {'scope': 'QF-S only; UTC throughout; historical observations, not causal estimates',
               'sources': {}, 'exchange': {}, 'evidence_gaps': [
                   'No tick path or exact historical orderbook; intrabar extrema order is unknown.',
                   'No immutable AI input snapshot or complete management-event history.',
                   'Python original ledgers omit fees/funding/slippage and original fixed quantity.',
                   'Closed-PnL rows are account events, not necessarily one-to-one strategy trades.',
                   'V5 persisted entry times are signal bar OPEN times; actual design enters at CLOSE.'],
               'input_hashes': {}}
    for f in [*(args.snapshot / n for n in SOURCES), *args.snapshot.glob('history*.sqlite')]:
        summary['input_hashes'][f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    summary['exchange'] = dict(closed_records=len(closes), execution_records=len(executions),
        order_records=len(orders), closed_pnl_usdt=sum(float(x['closedPnl']) for x in closes),
        closed_open_close_fees_usdt=sum(float(x.get('openFee', 0)) + float(x.get('closeFee', 0)) for x in closes),
        execution_types=dict(collections.Counter(x['execType'] for x in executions)),
        funding_cash_cost_usdt=sum(float(x.get('execFee') or 0) for x in executions if x['execType'] == 'Funding'),
        trade_execution_fees_usdt=sum(float(x.get('execFee') or 0) for x in executions if x['execType'] == 'Trade'),
        closed_wins=sum(float(x['closedPnl']) > 0 for x in closes),
        first_close_utc=stamp(min(int(x['createdTime']) for x in closes)) if closes else None,
        last_close_utc=stamp(max(int(x['createdTime']) for x in closes)) if closes else None)
    gross = [(float(x['avgExitPrice']) - float(x['avgEntryPrice'])) * float(x['closedSize'])
             * (1 if x['side'] == 'Sell' else -1) for x in closes]
    residuals = [float(x['closedPnl']) - (g - float(x.get('openFee', 0)) - float(x.get('closeFee', 0)))
                 for x, g in zip(closes, gross)]
    summary['exchange'].update(price_difference_gross_usdt=sum(gross),
        closed_pnl_minus_price_gross_plus_fees_usdt=sum(residuals),
        largest_single_row_reconciliation_residual_usdt=max(map(abs, residuals), default=0),
        reconciliation_note='Price gross uses reported average prices/closedSize. Residual may include funding, rounding, or other accounting; do not subtract fees again from closedPnl.')
    matched, csvrows = set(), []
    for name in SOURCES:
        with readonly(args.snapshot / name) as c:
            allrows = [dict(r) for r in c.execute('select * from ai_advice_track order by id')]
            alerts = {r['id']: dict(r) for r in c.execute('select * from ai_alert')} if name == 'quanforge.db' else {}
            ss = {'records': len(allrows), 'statuses': dict(collections.Counter(r['status'] for r in allrows))}
            trades = [r for r in allrows if r.get('entered_at') is not None]
            vals = [r['result_pct'] for r in trades if r['result_pct'] is not None]
            ss.update(entered=len(trades), priced_results=len(vals), positive=sum(v > 0 for v in vals),
                      mean_recorded_pct=statistics.mean(vals) if vals else None,
                      sum_recorded_pct=sum(vals), note='Pct sum is not account return; results have mixed cost bases.')
            if name != 'quanforge.db':
                eq = [(r[0], float(r[1])) for r in c.execute('select ts,equity from equity_snap order by rowid')]
                peak, dd = 200.0, 0.0
                for _, value in eq:
                    peak = max(peak, value)
                    dd = max(dd, (peak-value)/peak*100)
                ss.update(initial_equity=200.0, final_recorded_equity=eq[-1][1] if eq else None,
                          max_recorded_realized_drawdown_pct=dd,
                          equity_note='Recorded gross paper equity, not net/liquidation-aware equity.')
            full, floatloss, stops, missing = 0, 0, 0, 0
            previous = {}
            for r in trades:
                entered, settled = epoch(r['entered_at']), epoch(r.get('settled_at'))
                # V5 original timestamp labels are one hour early. Correct only the forensic window,
                # without changing the preserved ledger or claiming exact observed fill time.
                effective_entered = entered + (3600000 if name == 'paper_v5mech.db' else 0)
                effective_settled = settled + (3600000 if name == 'paper_v5mech.db' and settled else 0) if settled else None
                sym, buy = r['symbol'], r['action'] == 'BUY'
                entry = r.get('actual_entry') or r['entry']
                why = alerts.get(r.get('alert_id'), {})
                row = dict(source=name, trade_id=r['id'], mode=r.get('exec_mode') or 'PYTHON_PAPER',
                    version=r['sys_version'], symbol=sym, action=r['action'], status=r['status'],
                    ledger_entry_utc=stamp(entered), ledger_exit_utc=stamp(settled),
                    inferred_effective_entry_utc=stamp(effective_entered), entry=entry,
                    stop_loss_final=r['stop_loss'], take_profit_final=r['take_profit'],
                    recorded_result_pct=r['result_pct'], entry_reason=why.get('summary') or r.get('note') or 'NOT_RECORDED',
                    trigger_reason=why.get('trigger_reason', 'NOT_RECORDED'),
                    exit_evidence=r.get('note') or 'NO_EXIT_REASON_PERSISTED',
                    direction_supported_at_entry='UNPROVEN: no immutable decision snapshot',
                    preceding_30m_return_pct=None, preceding_30m_momentum_aligned=None,
                    observed_full_minutes=0, expected_full_minutes=0, full_price_coverage=False,
                    observed_mfe_pct=None, observed_mae_pct=None, observed_positive_then_loss=None,
                    first_final_sl_cross_bar_utc='', exit_delay_from_final_sl_cross_sec=None,
                    final_sl_cross_caveat='Final SL may have been moved; crossing is not original-SL proof.',
                    entry_fee_exact_usdt=None, entry_slippage_adverse_pct=None,
                    unique_close_candidate=False, candidate_close_net_usdt=None, candidate_close_fees_usdt=None,
                    funding_and_full_slippage='NOT_ATTRIBUTABLE per trade; account funding reported separately',
                    previous_same_symbol_minutes=None, previous_same_symbol_loss=None,
                    engineering_vs_strategy_loss_share='UNIDENTIFIABLE from available records')
                if sym in previous:
                    old = previous[sym]
                    row['previous_same_symbol_minutes'] = (effective_entered - old[0]) / 60000
                    row['previous_same_symbol_loss'] = old[1] is not None and old[1] < 0
                previous[sym] = effective_entered, r['result_pct']
                bars = prices.get(sym, [])
                symtimes = times.get(sym, [])
                cutoff = effective_entered // 60000 * 60000
                left = bisect.bisect_left(symtimes, cutoff - 30 * 60000)
                right = bisect.bisect_left(symtimes, cutoff)
                before = bars[left:right]
                if len(before) == 30 and all(b[0] == cutoff - (30 - i) * 60000 for i, b in enumerate(before)):
                    move = (before[-1][4] / before[0][1] - 1) * 100
                    row['preceding_30m_return_pct'] = move
                    row['preceding_30m_momentum_aligned'] = move > 0 if buy else move < 0
                if effective_settled and effective_settled >= effective_entered:
                    lo = bisect.bisect_left(symtimes, effective_entered)
                    hi = bisect.bisect_right(symtimes, effective_settled)
                    held, expected, mfe, mae = excursions(bars[lo:hi], effective_entered, effective_settled, entry, buy)
                    row.update(observed_full_minutes=len(held), expected_full_minutes=expected,
                               full_price_coverage=bool(expected and len(held) == expected),
                               observed_mfe_pct=mfe if held else None, observed_mae_pct=mae if held else None,
                               observed_positive_then_loss=(mfe > 0 and r['result_pct'] < 0)
                               if held and r['result_pct'] is not None else None)
                    full += row['full_price_coverage']
                    floatloss += bool(row['observed_positive_then_loss'])
                    missing += not bool(held)
                    for b in held:
                        if r['stop_loss'] and (b[3] <= r['stop_loss'] if buy else b[2] >= r['stop_loss']):
                            row['first_final_sl_cross_bar_utc'] = stamp(b[0])
                            row['exit_delay_from_final_sl_cross_sec'] = (effective_settled - b[0]) / 1000
                            stops += 1
                            break
                oid = r.get('order_id')
                fills = [e for e in entry_exec.get(oid, []) if e['execType'] == 'Trade']
                if fills:
                    row['entry_fee_exact_usdt'] = sum(float(e['execFee']) for e in fills)
                    qty = sum(float(e['execQty']) for e in fills)
                    avg = sum(float(e['execValue']) for e in fills) / qty if qty else 0
                    if avg and r['entry']:
                        row['entry_slippage_adverse_pct'] = (avg / r['entry'] - 1) * (100 if buy else -100)
                # A time/price/size candidate remains labelled a candidate, not a proven identity.
                if r.get('exec_mode') == 'DEMO' and settled and r.get('qty') and entry:
                    candidates = [x for x in closes if x['symbol'] == sym and x['side'] == ('Sell' if buy else 'Buy')
                        and abs(int(x['createdTime']) - settled) <= 180000
                        and abs(float(x['closedSize']) - r['qty']) <= max(1e-8, r['qty'] * .001)
                        and abs(float(x['avgEntryPrice']) / entry - 1) < .001]
                    if len(candidates) == 1 and candidates[0]['orderId'] not in matched:
                        x = candidates[0]; matched.add(x['orderId'])
                        row.update(unique_close_candidate=True, candidate_close_net_usdt=float(x['closedPnl']),
                                   candidate_close_fees_usdt=float(x['openFee']) + float(x['closeFee']))
                csvrows.append(row)
            ss.update(full_price_windows=full, observed_positive_then_loss=floatloss,
                      windows_with_final_sl_cross=stops, no_full_held_bar=missing)
            summary['sources'][name] = ss
    summary['exchange']['unique_java_close_candidates'] = len(matched)
    summary['exchange']['candidate_net_usdt'] = sum(float(x['closedPnl']) for x in closes if x['orderId'] in matched)
    summary['exchange']['candidate_fees_usdt'] = sum(float(x['openFee']) + float(x['closeFee']) for x in closes if x['orderId'] in matched)
    with (args.output / 'per-trade-evidence.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(csvrows[0]))
        writer.writeheader(); writer.writerows(csvrows)
    (args.output / 'trade-evidence-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
