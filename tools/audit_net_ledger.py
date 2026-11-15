"""Import immutable exchange evidence; exact order ownership only, never guessed exits.

Reads snapshots, not live accounts. Closed PnL is already net: fees are displayed
separately and never deducted from it again. Wallet NAV remains UNKNOWN without
cashflow and balance evidence.
"""
import argparse
import csv
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from verified_paper import Ledger, number, text


def records(folder, stem, identity):
    found = {}
    for file in sorted(folder.glob(stem+'-*.json')):
        response = json.loads(file.read_text(encoding='utf-8'))
        if response.get('retCode') != 0:
            raise ValueError('rejected evidence page: '+file.name)
        for row in response['result'].get('list', []):
            key = row[identity]
            if key in found and found[key] != row:
                raise ValueError('conflicting exchange identity: '+str(key))
            found[key] = row
    return list(found.values())


def audit(snapshot, ledger, output):
    executions = records(snapshot/'exchange','execution','execId')
    closes = records(snapshot/'exchange','closed','orderId')
    source = sqlite3.connect((snapshot/'quanforge.db').resolve().as_uri()+'?mode=ro',uri=True)
    source.row_factory = sqlite3.Row
    tracks = source.execute("select t.*,a.title as why,a.trigger_reason as trigger_reason from ai_advice_track t "
                            "left join ai_alert a on a.id=t.alert_id where t.exec_mode='DEMO'").fetchall()
    source.close()
    owners = {}
    for row in tracks:
        if row['order_id']:
            owners.setdefault(row['order_id'],[]).append(row['id'])
    with ledger.db:
        for execution in executions:
            ledger.append('bybit:exec:'+execution['execId'],'EXCHANGE_EXECUTION',int(execution['execTime']),execution)
        for closed in closes:
            ledger.append('bybit:closed:'+closed['orderId'],'EXCHANGE_CLOSED_PNL',int(closed['updatedTime']),closed)
    attributed = []
    for row in tracks:
        fills = [e for e in executions if e['execType']=='Trade' and e['orderId']==row['order_id']]
        unique = row['order_id'] is not None and len(owners[row['order_id']])==1
        known = unique and bool(fills) and all(e.get('feeCurrency')=='USDT' and e.get('execFee') not in (None,'') for e in fills)
        attributed.append(dict(track_id=row['id'],symbol=row['symbol'],side=row['action'],
            why=row['why'] or '',trigger=row['trigger_reason'] or '',entry_order=row['order_id'],
            entry_fills=len(fills) if unique else None,
            entry_fee_usdt=text(sum((number(e['execFee']) for e in fills),Decimal(0))) if known else None,
            complete_trade_net_usdt=None,
            missing='exit order ownership; funding allocation; stop event history; wallet cashflows'))
    def total(rows, field):
        if any(r.get(field) in (None,'') for r in rows):return None
        return text(sum((number(r[field]) for r in rows),Decimal(0)))
    trades = [e for e in executions if e['execType']=='Trade']
    funding = [e for e in executions if e['execType']=='Funding']
    fees_complete = all(e.get('feeCurrency')=='USDT' for e in trades)
    result = dict(scope='CAPTURED_DEMO_HISTORY_ONLY',executions=len(executions),closed_records=len(closes),
        trade_executions=len(trades),funding_executions=len(funding),
        closed_pnl_reported_usdt=total(closes,'closedPnl'),
        closed_open_fees_usdt=total(closes,'openFee'),closed_close_fees_usdt=total(closes,'closeFee'),
        trade_execution_fees_usdt=total(trades,'execFee') if fees_complete else None,
        funding_execution_cost_observed_usdt=total(funding,'execFee'),
        tracks=len(tracks),exact_entry_fee_tracks=sum(r['entry_fee_usdt'] is not None for r in attributed),
        complete_trade_net_tracks=0,wallet_reconciled=False,net_account_return=None,
        unknown=['complete exit ownership','wallet opening/closing balance and transfers',
                 'funding ownership','costs/slippage absent from source evidence'],
        note='Do not subtract fees or funding again from reported closedPnl; no causal loss percentages.')
    output.mkdir(parents=True,exist_ok=True)
    (output/'net-ledger-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    with (output/'net-ledger-tracks.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(attributed[0]) if attributed else ['track_id'])
        writer.writeheader();writer.writerows(attributed)
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--ledger',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    ledger=Ledger(args.ledger)
    try: print(json.dumps(audit(args.snapshot,ledger,args.output),indent=2))
    finally: ledger.close()
