"""Bounded public-data capture and frozen conditional-carry comparison.

Old two-year sample is explicitly reused research data, not unseen validation.
Raw replies are immutable; at most two attempts/request and 96 overall.
"""
import argparse
import csv
import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime,timezone
from pathlib import Path
import conditional_carry as engine
import crypto_edge_research as prior

ROOT=Path(__file__).resolve().parents[1]
PRIOR=ROOT/'docs/crypto-research-20261114'
PUBLIC={'/v5/market/kline','/v5/market/instruments-info','/v5/market/tickers'}


def source_hashes():
    return {name:prior.sha(Path(__file__).parent/name) for name in
            ('conditional_carry.py','crypto_edge_research.py','research_conditional_carry.py')}


class Capture:
    def __init__(self,directory):
        self.directory=directory;self.receipts=[]
        log=directory/'requests.jsonl'
        if log.exists(): self.receipts=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        self.cached={r['request_hash']:r for r in self.receipts if r['status']=='OK'}
    def get(self,path,**params):
        if path not in PUBLIC: raise ValueError('public endpoint allowlist')
        url='https://api.bybit.com'+path+'?'+urllib.parse.urlencode(sorted(params.items()))
        key=hashlib.sha256(url.encode()).hexdigest()
        if key in self.cached:
            record=self.cached[key];file=self.directory/record['file']
            if prior.sha(file)!=record['sha256']: raise ValueError('cached reply changed')
            return json.loads(file.read_text(encoding='utf-8'))['result']
        previous=sum(r['request_hash']==key for r in self.receipts)
        for _ in range(previous,2):
            if len(self.receipts)>=96: raise ValueError('overall public attempt budget')
            record=dict(at=datetime.now(timezone.utc).isoformat(),path=path,params=params,request_hash=key)
            try:
                request=urllib.request.Request(url,headers={'User-Agent':'QFS-conditional-research/1'})
                with urllib.request.urlopen(request,timeout=20) as response: raw=response.read()
                value=json.loads(raw)
                if value.get('retCode')!=0: raise ValueError('public API retCode '+str(value.get('retCode')))
                file=self.directory/f'public-{len(self.receipts)+1:03}.json'
                with file.open('xb') as f: f.write(raw)
                record.update(status='OK',file=file.name,sha256=prior.sha(file))
            except Exception as error:
                record.update(status='FAILED',error_type=type(error).__name__)
            self.receipts.append(record)
            with (self.directory/'requests.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(record)+'\n')
            print(json.dumps(dict(attempt=len(self.receipts),path=path,symbol=params.get('symbol'),status=record['status'])),flush=True)
            if record['status']=='OK': self.cached[key]=record;return value['result']
        raise RuntimeError('bounded request attempts exhausted')
    def bars(self,symbol,category,start,end):
        found={};cursor=end-1
        while cursor>=start:
            rows=self.get('/v5/market/kline',category=category,symbol=symbol,interval='60',start=start,end=cursor,limit=1000)['list']
            if not rows: raise ValueError('empty page')
            for row in rows:
                ts=int(row[0]);bar=[ts]+row[1:6]
                if start<=ts<end:
                    if ts in found and found[ts]!=bar: raise ValueError('conflicting hourly duplicate')
                    o,h,low,c=map(prior.n,bar[1:5])
                    if low<=0 or h<max(o,c) or low>min(o,c): raise ValueError('invalid OHLC')
                    found[ts]=bar
            following=min(int(row[0]) for row in rows)-1
            if following>=cursor: raise ValueError('pagination stalled')
            cursor=following
        if set(found)!=set(range(start,end,prior.HOUR)): raise ValueError('missing or misaligned prices')
        return [found[t] for t in sorted(found)]


def register(directory):
    directory.mkdir(parents=True,exist_ok=False)
    old=json.loads((PRIOR/'protocol.json').read_text(encoding='utf-8'))
    p=dict(registered_utc=datetime.now(timezone.utc).isoformat(),source_hashes=source_hashes(),
        prior_dataset_gzip_sha256=prior.sha(PRIOR/'dataset.json.gz'),start=old['start'],end_exclusive=old['end_exclusive'],
        symbols=['BTCUSDT','ETHUSDT'],capitals=['200','2000'],policies=['cash','static','conditional'],
        cost_cases=['base','double'],spot_fee='.001',perp_fee='.00055',slip='.0005',
        period_days=365,cases=48,label='EXPLORATORY_ON_PREVIOUSLY_SEEN_TWO_YEAR_SAMPLE',
        entry=dict(funding_history=21,minimum_positive_count=17,forecast='min(mean_last_21, mean_last_3) * 90 settlements',
            hurdle='forecast >= 1.5 * estimated four-leg roundtrip fees and slippage',
            rate_availability_delay_hours=1,decision_to_execution_delay_hours=1),
        exit=dict(funding='sum of last 3 published rates <= 0',short_margin_equity_fraction='.25',
            hedge_loss_fraction_of_entry_capital='.02',portfolio_peak_drawdown_stop='.03',cooldown_days=7),
        sizing='cash covers spot and full initial perp notional plus entry fees; quantities rounded down',
        no_auto_rebalance='coin units remain matched; no automatic collateral transfer or borrowing',
        static='enter start, hold to end unless reserve exhausted; identical price and fee model',
        fills='simultaneous two-leg modeled taker fills; not demonstrated actual fills',
        max_public_attempts=96,max_attempts_per_request=2,
        expiry_screen='BTC/ETH current dated futures only; exploratory quote screen, not an execution claim',
        no_optimisation='all cases retained; no retuning after inspecting results')
    prior.dump(directory/'protocol.json',p);return p


def capture(directory,p):
    client=Capture(directory);data={}
    for symbol in p['symbols']:
        data[symbol]={category:client.bars(symbol,category,p['start'],p['end_exclusive']) for category in ('spot','linear')}
    # Current dated-futures opportunity inventory. No private/account endpoints.
    inventory=[]
    for base in ('BTC','ETH'):
        response=client.get('/v5/market/instruments-info',category='linear',baseCoin=base,limit=1000)
        if response.get('nextPageCursor'): raise ValueError('expiry inventory pagination required')
        inventory.extend(response['list'])
    snapshot=dict(instruments=inventory,linear_tickers=client.get('/v5/market/tickers',category='linear')['list'],
        spot_tickers={symbol:client.get('/v5/market/tickers',category='spot',symbol=symbol)['list'][0] for symbol in p['symbols']})
    prior.dump(directory/'hourly-data.json',data);prior.dump(directory/'expiry-snapshot.json',snapshot)
    prior.dump(directory/'capture-manifest.json',dict(attempts=len(client.receipts),failed=sum(r['status']!='OK' for r in client.receipts),
        hourly_data_sha256=prior.sha(directory/'hourly-data.json'),expiry_snapshot_sha256=prior.sha(directory/'expiry-snapshot.json')))


def baseline():
    raw=gzip.decompress((PRIOR/'dataset.json.gz').read_bytes())
    expected=json.loads((PRIOR/'capture-manifest.json').read_text(encoding='utf-8'))['dataset_sha256']
    if hashlib.sha256(raw).hexdigest()!=expected: raise ValueError('prior dataset changed')
    return json.loads(raw)


def check_accounting(r,base,sf,pf):
    if r['status']!='HISTORICAL_MODEL': return dict(status='INVALIDATED_MARGIN_PATH',residual=None)
    cash=prior.n(r['initial_equity']);opening=None;fees=prior.D(0);income=prior.D(0)
    for event in r['orders']:
        q=prior.n(event['qty']);spot=prior.n(event['spot_fill']);perp=prior.n(event['perp_fill'])
        paid=q*(spot*sf+perp*pf);fees+=paid
        if event['action']=='OPEN_PAIR':
            cash-=q*spot+paid;opening=perp
            assert event['decision']['asof'] is None or event['at']>=event['decision']['asof']+prior.HOUR
        else:
            cash+=q*spot+q*(opening-perp)-paid;opening=None
    marks={b[0]:b for b in base['marks']}
    for trade in r['closed_trades']:
        expected=sum((prior.n(trade['qty'])*prior.n(marks[int(t)][1])*prior.n(rate)
            for t,rate in base['funding'].items() if trade['entry_at']<int(t)<=trade['exit_at'] and int(t)<r['end_exclusive']),prior.D(0))
        assert abs(expected-prior.n(trade['funding']))<prior.n('1e-20')
        income+=expected
    residual=cash+income-prior.n(r['final_equity'])
    assert abs(residual)<prior.n('1e-20')
    assert abs(fees-prior.n(r['fees']))<prior.n('1e-20')
    assert abs(income-prior.n(r['funding_income']))<prior.n('1e-20')
    return dict(status='RECONCILED',residual=prior.s(residual))


def evaluate(directory,p):
    if source_hashes()!=p['source_hashes']: raise ValueError('registered source changed')
    if prior.sha(PRIOR/'dataset.json.gz')!=p['prior_dataset_gzip_sha256']: raise ValueError('prior package changed')
    manifest=json.loads((directory/'capture-manifest.json').read_text(encoding='utf-8'))
    if prior.sha(directory/'hourly-data.json')!=manifest['hourly_data_sha256']: raise ValueError('hourly data changed')
    old=baseline();hourly=json.loads((directory/'hourly-data.json').read_text(encoding='utf-8'));runs=[]
    for symbol in p['symbols']:
        b=old[symbol];sl=b['spot_instrument']['lotSizeFilter'];pl=b['linear_instrument']['lotSizeFilter']
        step=max(prior.n(sl['basePrecision']),prior.n(pl['qtyStep']))
        for year in (0,1):
            start=p['start']+year*365*prior.DAY;end=start+365*prior.DAY
            for capital in p['capitals']:
                for cost in p['cost_cases']:
                    mult=1 if cost=='base' else 2
                    sf=prior.n(p['spot_fee'])*mult;pf=prior.n(p['perp_fee'])*mult;slip=prior.n(p['slip'])*mult
                    for policy in p['policies']:
                        r=engine.replay(hourly[symbol]['spot'],hourly[symbol]['linear'],b['marks'],b['funding'],start,end,policy,
                            capital,sf,pf,slip,step,max(prior.n(sl['minOrderQty']),prior.n(pl['minOrderQty'])),
                            max(prior.n(sl['minOrderAmt']),prior.n(pl['minNotionalValue'])))
                        r.update(symbol=symbol,period=year+1,start=start,end_exclusive=end,capital=capital,cost_case=cost,policy=policy)
                        r['independent_accounting']=check_accounting(r,b,sf,pf);runs.append(r)
    prior.dump(directory/'results.json',dict(source_hashes=source_hashes(),runs=runs))
    cols=['symbol','period','capital','cost_case','policy','status','return_pct','net_pnl','hourly_close_max_drawdown_pct',
        'entries','leg_orders','fees','funding_income','slippage_diagnostic','invested_hours','blocked_minimum','halted_by_drawdown']
    with (directory/'comparison.csv').open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');writer.writeheader();writer.writerows(runs)
    print(json.dumps(dict(cases=len(runs),accounting_reconciled=sum(r['independent_accounting']['status']=='RECONCILED' for r in runs))),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['capture','resume','replay'])
    parser.add_argument('--directory',type=Path,required=True);args=parser.parse_args();directory=args.directory
    if args.action=='capture': p=register(directory)
    else: p=json.loads((directory/'protocol.json').read_text(encoding='utf-8'))
    if source_hashes()!=p['source_hashes']: raise ValueError('registered source changed')
    if args.action in ('capture','resume'): capture(directory,p)
    else: evaluate(directory,p)


if __name__=='__main__': main()
