"""Reconcile captured transaction-log equations and balance chains, including timestamp ties.

No guessed ordering by UUID; no claim that category-filtered captures cover an entire account.
"""
import argparse
import collections
import json
from pathlib import Path
from decimal import Decimal
from verified_paper import Ledger, number, text


def reconcile(rows):
    unique={}
    for row in rows:
        if row['currency']!='USDT':raise ValueError('mixed currency')
        if row['id'] in unique and unique[row['id']]!=row:raise ValueError('conflicting cashflow id')
        unique[row['id']]=row
    rows=list(unique.values())
    violations=[];groups=collections.defaultdict(list)
    for row in rows:
        expected=number(row.get('cashFlow') or 0)+number(row.get('funding') or 0)-number(row.get('fee') or 0)
        if expected!=number(row['change']):violations.append(row['id'])
        groups[int(row['transactionTime'])].append(row)
    opening=previous=None;gaps=[];ambiguous=[]
    for ts,group in sorted(groups.items()):
        edges=[(number(r['cashBalance'])-number(r['change']),number(r['cashBalance'])) for r in group if number(r['change'])!=0]
        if not edges:
            balances={number(r['cashBalance']) for r in group}
            if len(balances)!=1:ambiguous.append(ts);continue
            start=end=next(iter(balances))
        else:
            starts=[a for a,_ in edges if a not in {b for _,b in edges}]
            if len(starts)!=1:ambiguous.append(ts);continue
            start=end=starts[0];remaining=list(edges)
            while remaining:
                candidates=[edge for edge in remaining if edge[0]==end]
                if len(candidates)!=1:ambiguous.append(ts);break
                edge=candidates[0];end=edge[1];remaining.remove(edge)
            if remaining:continue
        if opening is None:opening=start
        if previous is not None and previous!=start:gaps.append(dict(at=ts,unexplained=text(start-previous)))
        previous=end
    def total(field,predicate=lambda row:True):
        return sum((number(r.get(field) or 0) for r in rows if predicate(r)),Decimal(0))
    transfers=total('change',lambda row:row['type'].startswith('TRANSFER'))
    changes=total('change')
    residual=previous-opening-changes if previous is not None and opening is not None else None
    return dict(rows=len(rows),type_counts=dict(collections.Counter(r['type'] for r in rows)),
        row_equation_violations=len(violations),ambiguous_timestamp_groups=ambiguous,balance_gaps=gaps,
        opening_cash_inferred_from_first_transaction=text(opening) if opening is not None else None,
        final_recorded_cash=text(previous) if previous is not None else None,
        gross_cashflow_all_types=text(total('cashFlow')),fees=text(total('fee')),funding_received_signed=text(total('funding')),
        observed_change=text(changes),transfers_net=text(transfers),change_excluding_transfers=text(changes-transfers),
        chain_residual=text(residual) if residual is not None else None,
        recorded_balance_chain_reconciled=bool(rows) and not violations and not gaps and not ambiguous and residual==0,
        full_account_activity_coverage=False,account_rate_of_return=None,
        note='Captured linear USDT logs plus bounded gap queries; chain reconciliation is not a complete NAV/return audit.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--ledger',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execution-snapshot',type=Path)
    args=parser.parse_args();rows=[]
    for path in list(args.capture.glob('cashflow-history-*.json'))+list(args.capture.glob('cashflow-gaps-*.json')):
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('retCode')!=0:raise ValueError('rejected cashflow page')
        rows.extend(data['result']['list'])
    result=reconcile(rows)
    if args.execution_snapshot:
        from audit_net_ledger import records
        executions=records(args.execution_snapshot/'exchange','execution','execId')
        ids={r['execId'] for r in executions}
        matched={r['id']:r for r in rows if r.get('tradeId') in ids}
        def linked_total(field):return text(sum((number(r.get(field) or 0) for r in matched.values()),Decimal(0)))
        result['exact_execution_linked_cashflows']=dict(rows=len(matched),captured_executions=len(ids),
            change=linked_total('change'),gross_cashflow=linked_total('cashFlow'),fees=linked_total('fee'),
            funding_received_signed=linked_total('funding'),
            note='Exact tradeId=execId scope; do not mix this cash ledger delta with closedPnl or full-window totals.')
    ledger=Ledger(args.ledger)
    try:
        with ledger.db:
            for row in rows:ledger.append('bybit:cash:'+row['id'],'EXCHANGE_CASHFLOW',int(row['transactionTime']),row)
    finally:ledger.close()
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
