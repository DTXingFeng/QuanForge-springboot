"""Frozen 90-day five-minute candidate comparison. Public capture and offline replay.

Three independent 30-day windows, four policies, base/double costs. No optimiser.
Historical OHLC stop ordering/quotes are explicitly modeled, never forward fills.
"""
import argparse
import collections
import copy
import hashlib
import json
import time
from contextlib import contextmanager
from pathlib import Path
from paper_vnext_strategy import INTERVAL,HOUR,VERSION,POLICIES,feature_series,evaluate,canonical
from paper_vnext_ledger import PaperBook,n,text
from paper_vnext_market import Market,atomic_json

DAY=86400000


def digest(path):return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
def sources():return {name:digest(Path(__file__).with_name(name)) for name in
    ['paper_vnext_strategy.py','paper_vnext_ledger.py','paper_vnext_market.py','paper_vnext_research.py']}
def write(path,value):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2)


def register(root):
    root.mkdir(parents=True,exist_ok=False);end=int(time.time()*1000)//DAY*DAY
    p=dict(version=VERSION,registered_utc_ms=int(time.time()*1000),symbol='XRPUSDT',start=end-90*DAY,end_exclusive=end,
        warmup_hours=250,periods=3,period_days=30,policies=list(POLICIES),cost_cases=['base','double'],capital='20',
        fee='.00055',slip='.0005',historical_half_spread='.00005',cases=24,sources=sources(),
        research='retrospective exploratory 5m study; previous hourly XRP history already examined',
        entries='decision at closed bar; next bar open proxy only; unobserved intrabar entries not invented',
        exits='adverse gap open; SL before TP when both touch; no favorable TP on entry bar except executable close',
        protection='same ledger rule, evaluated at five-minute closes; source and protected wallets share admissions',
        funding='actual settlement rate times hourly mark open; equal-time entry excluded by settlement guard',
        stress='double fee, slip and assumed spread; strategy cost hurdles react to the same cost case',
        gate='all three windows positive after base and doubled costs, max sampled DD <=10%, >=30 primary closes total; not proof of profitability',
        deployment='fixed selector remains an explicitly unvalidated PAPER experiment, never auto real/Demo',
        max_requests=64,max_attempts_per_query=2,no_parameter_search=True)
    write(root/'protocol.json',p);return p


def capture(root,p,proxy):
    market=Market(root/'receipts',proxy,budget=p['max_requests']);cache=root/'cache';cache.mkdir(exist_ok=True)
    def get(path,**params):
        key=hashlib.sha256(canonical([path,params]).encode()).hexdigest();f=cache/(key+'.json')
        if f.exists():return json.loads(f.read_text())
        errors=[]
        for _ in range(2):
            try:
                result=market.get(path,**params);write(f,result);return result
            except Exception as e:errors.append(type(e).__name__)
        write(cache/(key+'-failed.json'),dict(errors=errors));raise RuntimeError('bounded historical query failed')
    start=p['start']-p['warmup_hours']*HOUR;end=p['end_exclusive'];bars={};cursor=end-1;pages=0
    while cursor>=start:
        rows=get('/v5/market/kline',category='linear',symbol=p['symbol'],interval='5',start=start,end=cursor,limit=1000)['result']['list']
        if not rows:raise ValueError('empty history page')
        for b in rows:
            ts=int(b[0]);bar=[ts]+[float(v) for v in b[1:6]]
            if start<=ts<end:
                if ts in bars and bars[ts]!=bar:raise ValueError('conflicting history')
                bars[ts]=bar
        following=min(int(b[0]) for b in rows)-1
        if following>=cursor:raise ValueError('history pagination failed')
        cursor=following;pages+=1;print(json.dumps(dict(stage='bars',pages=pages,stored=len(bars))),flush=True)
    if set(bars)!=set(range(start,end,INTERVAL)):raise ValueError('history gap')
    marks={};cursor=end-1
    while cursor>=p['start']:
        rows=get('/v5/market/mark-price-kline',category='linear',symbol=p['symbol'],interval='60',start=p['start'],end=cursor,limit=1000)['result']['list']
        if not rows:raise ValueError('mark history missing')
        for b in rows:
            if p['start']<=int(b[0])<end:marks[int(b[0])]=b[1]
        cursor=min(int(b[0]) for b in rows)-1
    rates={};cursor=end-1
    while cursor>=p['start']:
        rows=get('/v5/market/funding/history',category='linear',symbol=p['symbol'],startTime=p['start'],endTime=cursor,limit=200)['result']['list']
        if not rows:break
        for r in rows:
            if p['start']<=int(r['fundingRateTimestamp'])<end:rates[int(r['fundingRateTimestamp'])]=r['fundingRate']
        cursor=min(int(r['fundingRateTimestamp']) for r in rows)-1
    if set(rates)!=set(range(p['start'],end,8*HOUR)):raise ValueError('unsupported funding schedule/gap')
    if not set(rates).issubset(marks):raise ValueError('funding mark missing')
    # Metadata is public; source code uses no account client.
    lot=market.instrument(p['symbol'])
    data=dict(bars=[bars[t] for t in sorted(bars)],marks=marks,rates=rates,lot=lot)
    write(root/'dataset.json',data);write(root/'capture-manifest.json',dict(dataset_sha256=hashlib.sha256((root/'dataset.json').read_bytes()).hexdigest(),
        bars=len(bars),rates=len(rates),marks=len(marks),source_hashes=sources()))


class FastBook(PaperBook):
    """Research-only in-memory event sink; identical execution/state methods.

    Transaction/persistence behavior is tested on the real SQLite ledger separately.
    """
    def __init__(self,seed):
        self.logs=[];self.seen=set();self.kinds=collections.Counter();super().__init__(':memory:',seed)
    @contextmanager
    def atomic(self):yield
    def emit(self,kind,key,at,payload):
        if key in self.seen:return False
        self.seen.add(key);self.kinds[kind]+=1
        if kind not in ('QUOTE','FRAME'):self.logs.append(dict(kind=kind,at=at,payload=copy.deepcopy(payload)))
        return True


def replay(data,bars,frames,start,end,policy,multiplier):
    book=FastBook(dict(start=start,watermark=start//INTERVAL-1,cost_multiplier=multiplier,policy=policy))
    spread=n('.00005')*multiplier;lot=data['lot'];rates={int(t):r for t,r in data['rates'].items()};marks={int(t):v for t,v in data['marks'].items()}
    curve=[];signals=0;hist_cost=float(n('.0022')*multiplier)
    def quote(at,reference,bid=None,ask=None):
        mid=n(reference)
        q=dict(symbol='XRPUSDT',at=at,bid=text(mid*(1-spread) if bid is None else bid),
            ask=text(mid*(1+spread) if ask is None else ask),mark=text(mid),bid_size='10000000',ask_size='10000000',
            next_funding=(at//(8*HOUR)+1)*(8*HOUR),source='HISTORICAL_OHLC_MODEL')
        book.quote(q,at)
        for key,event in list(book.state['funding_pending'].items()):
            if event['at'] not in rates or event['at'] not in marks:raise ValueError('missing owned funding')
            book.apply_funding(key,rates[event['at']],marks[event['at']],at)
        return q
    def offer(frame,at):
        nonlocal signals
        decision=evaluate(frame,policy,hist_cost)
        if decision['action']:
            signals+=1;sign=1 if decision['action']=='BUY' else -1
            book.offer(dict(id=at//INTERVAL,symbol='XRPUSDT',action=decision['action'],entry=decision['reference']*(1+sign*.003),
                stop_loss=decision['stop'],take_profit=decision['target'],created_at=at,strategy=decision.get('selected',policy),input_hash=decision['input_hash']),lot,at)
    first=next(i for i,b in enumerate(bars) if b[0]==start)
    if first>0:offer(frames[first-1],start)
    for i in range(first,len(bars)):
        ts,o,high,low,c,_=bars[i]
        if ts>=end:break
        quote(ts+1,o)
        if book.state['pending']:
            # OHLC cannot prove that a later tick inside the first 60s was executable.
            book.emit('RESEARCH_UNOBSERVED_ENTRY',f'unobserved:{ts}',ts+1,{})
            book.state['pending']=None
        levels=[]
        for a in book.state['arms'].values():
            pos=a['position']
            if pos:
                stop=n(pos['stop']);buy=pos['side']=='BUY'
                if (n(low)*(1-spread)<=stop if buy else n(high)*(1+spread)>=stop):levels.append((stop,buy))
        # All concurrent positions have the same side and entry by paired admission.
        levels=sorted(set(levels),key=lambda x:x[0],reverse=bool(levels and levels[0][1]))
        for j,(stop,buy) in enumerate(levels):
            quote(ts+INTERVAL-20+j,stop,bid=stop if buy else stop*(1-2*spread),ask=stop*(1+2*spread) if buy else stop)
        for j,a in enumerate(book.state['arms'].values()):
            pos=a['position']
            if pos and pos['entered_at']<ts:
                target=n(pos['tp']);buy=pos['side']=='BUY'
                if (n(high)*(1-spread)>=target if buy else n(low)*(1+spread)<=target):
                    quote(ts+INTERVAL-10+j,target,bid=target if buy else target*(1-2*spread),ask=target*(1+2*spread) if buy else target)
        close_at=ts+INTERVAL if ts+INTERVAL<end else end-1
        closing=quote(close_at,c)
        if ts+INTERVAL<end:
            book.protect(closing,close_at,ts+INTERVAL);offer(frames[i],ts+INTERVAL)
        if (ts+INTERVAL)%DAY==0 or ts+INTERVAL==end:
            curve.append(dict(at=ts+INTERVAL,primary=book.state['arms']['profit_protect']['equity_liquidation'],
                control=book.state['arms']['source_exit']['equity_liquidation']))
    book.finish({'XRPUSDT':closing},end-1)
    state=book.state;raw=book.report()
    results={name:dict(final_equity=a['cash'],net_pnl=text(n(a['cash'])-20),return_pct=text((n(a['cash'])/20-1)*100),
        max_drawdown_pct=text(n(a['max_drawdown'])*100),fees=a['fees'],funding_cost=a['funding_cost'],closed=len(a['trades']),
        wins=sum(n(t['net_before_funding'])-n(t['funding_cost'])>0 for t in a['trades']),
        invalid=a['invalid'],ledger_cash_residual=raw['accounting'][name]['ledger_cash_residual'],trades=a['trades']) for name,a in state['arms'].items()}
    assert all(v['ledger_cash_residual']=='0' for v in results.values())
    book.close();return dict(start=start,end_exclusive=end,policy=policy,cost_multiplier=multiplier,signals=signals,
        entry_events=book.kinds['ENTRY'],exit_events=book.kinds['EXIT'],wallets=results,curve=curve)


def evaluate_study(root,p):
    if p['sources']!=sources():raise ValueError('frozen research sources changed')
    raw=(root/'dataset.json').read_bytes();manifest=json.loads((root/'capture-manifest.json').read_text())
    if hashlib.sha256(raw).hexdigest()!=manifest['dataset_sha256']:raise ValueError('data hash changed')
    data=json.loads(raw);print('building causal features',flush=True);bars,frames=feature_series(data['bars'],p['end_exclusive']);runs=[]
    for period in range(3):
        start=p['start']+period*30*DAY;end=start+30*DAY
        for mult in (1,2):
            for policy in POLICIES:
                result=replay(data,bars,frames,start,end,policy,mult);result['period']=period+1;runs.append(result)
                print(json.dumps(dict(period=period+1,cost=mult,policy=policy,net=result['wallets']['profit_protect']['net_pnl'])),flush=True)
    gates={}
    for policy in POLICIES:
        candidates=[r for r in runs if r['policy']==policy]
        gates[policy]=dict(historical_gate_passed=policy!='cash' and all(n(r['wallets']['profit_protect']['net_pnl'])>0 and
            n(r['wallets']['profit_protect']['max_drawdown_pct'])<=10 and not r['wallets']['profit_protect']['invalid'] for r in candidates)
            and sum(r['wallets']['profit_protect']['closed'] for r in candidates if r['cost_multiplier']==1)>=30,
            forward_paper_passed=False)
    write(root/'results.json',dict(protocol=p,runs=runs,gates=gates))
    write(root/'research-summary.json',dict(version=VERSION,period_days=30,windows=3,gates=gates,
        source='HISTORICAL_OHLC_MODEL',forward_paper_passed=False,
        cases=[{k:r[k] for k in ['period','cost_multiplier','policy','start','end_exclusive']}|{'primary':{k:v for k,v in r['wallets']['profit_protect'].items() if k!='trades'}} for r in runs]))


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('action',choices=['capture','replay']);a.add_argument('--root',type=Path,required=True);a.add_argument('--proxy');args=a.parse_args()
    p=register(args.root) if args.action=='capture' else json.loads((args.root/'protocol.json').read_text())
    if args.action=='capture':capture(args.root,p,args.proxy)
    else:evaluate_study(args.root,p)
