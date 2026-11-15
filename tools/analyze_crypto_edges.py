"""Independent accounting checks and descriptive analysis of the frozen experiment.

Does not change signals, replay trades or select parameters. No network access.
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from crypto_edge_research import D,n,s,sha,dump,DAY


def analyze(directory):
    p=json.loads((directory/'protocol.json').read_text(encoding='utf-8'))
    data=json.loads((directory/'dataset.json').read_text(encoding='utf-8'))
    results=json.loads((directory/'results.json').read_text(encoding='utf-8'))
    checks=[];funding=[];screens=[]
    for r in results['runs']:
        multiplier=1 if r['cost_case']=='base' else 2
        sf=n(p['costs']['spot_fee_per_side'])*multiplier
        pf=n(p['costs']['perp_fee_per_side'])*multiplier
        slip=n(p['costs']['adverse_slippage_per_leg'])*multiplier
        e=data[r['symbol']]
        if r['arm']=='funding_carry':
            q=n(r['qty']);spot={b[0]:b for b in e['spot']};perp={b[0]:b for b in e['linear']}
            marks={b[0]:b for b in e['marks']};start=r['start'];end=r['end_exclusive']
            income=sum((q*n(marks[int(t)][1])*n(rate) for t,rate in e['funding'].items() if start<int(t)<end),D(0))
            # Independent four-cashflow ledger, including close of the short obligation.
            buys=q*(n(spot[start][1])*(1+slip)+n(perp[end-DAY][4])*(1+slip))
            sells=q*(n(perp[start][1])*(1-slip)+n(spot[end-DAY][4])*(1-slip))
            fees=q*(sf*(n(spot[start][1])*(1+slip)+n(spot[end-DAY][4])*(1-slip))+
                    pf*(n(perp[start][1])*(1-slip)+n(perp[end-DAY][4])*(1+slip)))
            expected=n(200)+sells-buys+income-fees
            assert abs(income-n(r['funding_income']))<n('1e-20')
            assert abs(fees-n(r['fees']))<n('1e-20')
        else:
            expected=n(200);fees=n(0)
            for event in r['events']:
                amount=n(event['qty'])*n(event['price']);fees+=amount*sf
                expected+=amount if event['side']=='SELL' else -amount
                assert event['signal_at'] is None or event['signal_at']+DAY==event['at']
            expected-=fees
            assert abs(fees-n(r['fees']))<n('1e-20')
        residual=expected-n(r['final_equity'])
        assert abs(residual)<n('1e-20'),r
        assert abs(n(r['curve'][-1]['equity'])-expected)<n('1e-20')
        checks.append(dict(symbol=r['symbol'],period=r['period'],arm=r['arm'],cost_case=r['cost_case'],ledger_residual=s(residual)))
    for symbol,e in data.items():
        marks={b[0]:b for b in e['marks']}
        for period in (1,2):
            r=next(r for r in results['runs'] if r['symbol']==symbol and r['period']==period and r['arm']=='funding_carry' and r['cost_case']=='base')
            values=[(int(t),n(rate)) for t,rate in e['funding'].items() if r['start']<int(t)<r['end_exclusive']]
            monthly=defaultdict(D);negative=0;longest=0;current=0
            for t,rate in sorted(values):
                monthly[datetime.fromtimestamp(t/1000,timezone.utc).strftime('%Y-%m')]+=n(r['qty'])*n(marks[t][1])*rate
                current=current+1 if rate<0 else 0;longest=max(longest,current);negative+=rate<0
            funding.append(dict(symbol=symbol,period=period,events=len(values),negative_events=negative,
                longest_negative_funding_streak=longest,monthly_gross_income={k:s(v) for k,v in sorted(monthly.items())},
                negative_calendar_month_buckets=sum(v<0 for v in monthly.values()),
                note='first and last calendar-month buckets may be partial; no entry/exit costs allocated to these buckets'))
        ticker=e['ticker_snapshot'];bid=n(ticker['bid1Price']);ask=n(ticker['ask1Price'])
        screens.append(dict(symbol=symbol,snapshot_bid=s(bid),snapshot_ask=s(ask),
            snapshot_quoted_spread_bps=s((ask-bid)/((ask+bid)/2)*10000),
            assumed_VIP0_perp_roundtrip_maker_fee_bps='4',
            note='one snapshot only; not a market making backtest; no rebates or queue priority assumed'))
    return dict(independent_ledger_checks=checks,all_40_ledgers_reconcile=True,
        funding_period_details=funding,market_making_cost_screen=screens,
        dataset_sha256=sha(directory/'dataset.json'),results_sha256=sha(directory/'results.json'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args();result=analyze(args.directory);dump(args.directory/'accounting-analysis.json',result)
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
