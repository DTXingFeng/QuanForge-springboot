"""Bounded, preregistered historical strategy comparison. Public GET only.

Independent research companion; never changes the running Java/Python services.
Every arm and cost case is retained. Historical checks are not future evidence.
"""
import argparse
import hashlib
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path
from decimal import Decimal
from verified_paper import ema, number, text, canonical, bars_snapshot

INTERVAL=900000
ARMS=['ema_cross','breakout','mean_reversion','cash']
ALLOWED={'/v5/market/kline','/v5/market/mark-price-kline','/v5/market/funding/history','/v5/market/instruments-info'}


def signals(bars,name):
    if name not in ARMS:raise ValueError('unknown arm')
    output=[]
    for i in range(len(bars)):
        side=None;atr=0.
        if i>=239:
            history=bars[i-239:i+1];closes=[b[4] for b in history]
            fast,slow=ema(closes,20),ema(closes,60)
            if name=='ema_cross':
                prior=ema(closes[:-1],20)-ema(closes[:-1],60)
                side='BUY' if prior<=0<fast-slow else 'SELL' if prior>=0>fast-slow else None
            elif name=='breakout':
                prior=history[-21:-1]
                side='BUY' if closes[-1]>max(b[2] for b in prior) and fast>slow else 'SELL' if closes[-1]<min(b[3] for b in prior) and fast<slow else None
            elif name=='mean_reversion':
                center=statistics.mean(closes[-20:]);sd=statistics.pstdev(closes[-20:])
                z=(closes[-1]-center)/sd if sd>0 else 0
                side='SELL' if z>=2 else 'BUY' if z<=-2 else None
            trs=[max(b[2]-b[3],abs(b[2]-a[4]),abs(b[3]-a[4])) for a,b in zip(history,history[1:])]
            atr=sum(trs[-14:])/14
        output.append((side,atr))
    return output


def replay(bars,decisions,funding,marks,start,end,fee,slip):
    """Causal close signal -> next open; fixed SL/TTL and funding before boundary orders.

    All arithmetic money is Decimal. Marked drawdown is bar-close sampled, not tick DD.
    No terminal forced close: remaining exposure remains in NAV and is disclosed.
    """
    initial=number(200);cash=initial;peak=initial;maxdd=Decimal(0)
    p=None;pending=None;day=None;day_start=initial;last_nav=initial;halted=False;daily_halt=False
    fees=Decimal(0);fund=Decimal(0);slippage=Decimal(0);gross_realized=Decimal(0)
    trades=[];entries=0;day_values={};signals_seen=0;entry_events=[]
    def fill(reference,side,qty):
        nonlocal fees,slippage
        price=number(reference)*(1+number(slip)*(1 if side=='BUY' else -1))
        paid=price*qty*number(fee)
        fees+=paid;slippage+=abs(price-number(reference))*qty
        return price,paid
    def close(reference,ts,reason):
        nonlocal p,cash,gross_realized
        price,paid=fill(reference,'SELL' if p['side']=='BUY' else 'BUY',p['qty'])
        gross=(price-p['entry'])*p['qty']*(1 if p['side']=='BUY' else -1)
        cash+=gross-paid;gross_realized+=gross
        trades.append(dict(side=p['side'],entered=p['entered'],exited=ts,entry=text(p['entry']),exit=text(price),
            qty=text(p['qty']),reason=reason,net=text(gross-p['entry_fee']-paid-p['funding']),
            fees=text(p['entry_fee']+paid),funding=text(p['funding'])))
        p=None
    def mark(price):
        return cash+((number(price)-p['entry'])*p['qty']*(1 if p['side']=='BUY' else -1) if p else Decimal(0))
    for i,bar in enumerate(bars):
        ts,o,h,low,c,_=bar
        if not start<=ts<end:continue
        current_day=ts//86400000
        if current_day!=day:day=current_day;day_start=last_nav;daily_halt=False
        if p and ts in funding:
            if ts not in marks:raise ValueError('funding mark missing')
            cost=p['qty']*number(marks[ts])*number(funding[ts])*(1 if p['side']=='BUY' else -1)
            cash-=cost;fund+=cost;p['funding']+=cost
        # TTL is known in advance and exits at the current open, not one bar late.
        if p and ts-p['entered']>=96*INTERVAL:close(o,ts,'TTL')
        if pending and p and p['side']!=pending[0]:close(o,ts,'REVERSE')
        nav=mark(o)
        peak=max(peak,nav);maxdd=max(maxdd,1-nav/peak)
        halted=halted or nav<=peak*number('.90') or nav<=0
        daily_halt=daily_halt or nav<=day_start*number('.97')
        blocked=halted or daily_halt
        if pending and not p and not blocked and nav>0:
            side,atr=pending;distance=number(atr)*number('1.2')
            if distance<=0:raise ValueError('nonpositive ATR')
            cap=nav/(number(o)*(1+number(slip))*(1+number(fee)))
            qty=min(nav*number('.01')/distance,cap)
            entry,paid=fill(o,side,qty);cash-=paid;entries+=1
            stop=entry-distance if side=='BUY' else entry+distance
            if stop<=0:raise ValueError('invalid stop')
            p=dict(side=side,qty=qty,entry=entry,stop=stop,entered=ts,entry_fee=paid,funding=Decimal(0))
            entry_events.append(dict(at=ts,side=side,price=text(entry),signal_asof=ts))
        pending=None
        if p and ((number(low)<=p['stop']) if p['side']=='BUY' else (number(h)>=p['stop'])):
            stop=min(number(o),p['stop']) if p['side']=='BUY' else max(number(o),p['stop'])
            close(stop,ts+INTERVAL,'SL_INTRABAR_TIME_UNKNOWN')
        nav=mark(c);peak=max(peak,nav);maxdd=max(maxdd,1-nav/peak)
        halted=halted or nav<=peak*number('.90') or nav<=0
        daily_halt=daily_halt or nav<=day_start*number('.97')
        day_values[day]=text(nav);last_nav=nav
        side,atr=decisions[i]
        if side:
            signals_seen+=1
            if not halted:pending=(side,atr)
    open_position={k:text(v) if isinstance(v,Decimal) else v for k,v in p.items()} if p else None
    unrealized=last_nav-cash
    residual=last_nav-(initial+gross_realized-fees-fund+unrealized)
    return dict(entries=entries,closed=len(trades),wins=sum(number(t['net'])>0 for t in trades),
        losses=sum(number(t['net'])<0 for t in trades),signals=signals_seen,
        final_equity=text(last_nav),net_pnl=text(last_nav-initial),return_pct=text((last_nav/initial-1)*100),
        close_sampled_max_drawdown_pct=text(maxdd*100),fees=text(fees),funding_cost_signed=text(fund),
        slippage_diagnostic=text(slippage),realized_gross_after_slippage=text(gross_realized),
        unrealized_after_slippage=text(unrealized),accounting_residual=text(residual),
        hard_drawdown_halt=halted,open_position=open_position,trades=trades,entry_events=entry_events,
        daily_closing_equity=day_values,
        exit_delay_ms=None,exit_delay_note='OHLC cannot identify intrabar stop time; fill is modeled, not observed')


class Capture:
    def __init__(self,folder,budget):self.folder,self.budget,self.requests=folder,budget,[]
    def get(self,endpoint,params):
        if endpoint not in ALLOWED or len(self.requests)>=self.budget:raise ValueError('endpoint/budget refused')
        identity=len(self.requests);request=dict(endpoint=endpoint,params=params,at=int(time.time()*1000))
        self.requests.append(request)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('https://api.bybit.com'+endpoint+'?'+urllib.parse.urlencode(params),timeout=20) as response:
            data=json.load(response)
        file=self.folder/f'public-{identity:02d}.json';file.write_text(json.dumps(data),encoding='utf-8')
        request['sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
        if data.get('retCode')!=0:raise ValueError('public data rejected')
        return data['result']
    def candles(self,endpoint,start,end):
        found={};right=end-1
        for _ in range(12):
            response=self.get(endpoint,dict(category='linear',symbol='BTCUSDT',interval=15,limit=1000,start=start,end=right))
            rows=response.get('list',[])
            if not rows:break
            for raw in rows:
                row=(int(raw[0]),*[float(x) for x in raw[1:6]])
                if len(row)==5:row=(*row,0.)
                if row[0] in found and found[row[0]]!=row:raise ValueError('conflicting pages')
                found[row[0]]=row
            earliest=min(int(r[0]) for r in rows)
            if earliest<=start:break
            if earliest>=right:raise ValueError('no page progress')
            right=earliest-1
        bars,_=bars_snapshot(list(found.values()),INTERVAL,end,0)
        if len(bars)!=(end-start)//INTERVAL or bars[0][0]!=start:raise ValueError('incomplete fixed sample')
        return bars


def replay_cached(baseline,private,output):
    """Re-run engineering fixes on the exact registered sample, without any HTTP or date changes."""
    before=json.loads(baseline.read_text(encoding='utf-8'));protocol=before['protocol']
    data_file=private/'dataset.json'
    if hashlib.sha256(data_file.read_bytes()).hexdigest()!=before['dataset_sha256']:raise ValueError('dataset changed')
    data=json.loads(data_file.read_text(encoding='utf-8'));bars=[tuple(b) for b in data['bars']]
    rates={int(k):v for k,v in data['funding'].items()};marks={b[0]:b[1] for b in data['marks']}
    results=[]
    for arm in protocol['arms']:
        decisions=signals(bars,arm)
        for period,left,right in [('first_60_days',protocol['start_ms'],protocol['split_ms']),('last_30_days',protocol['split_ms'],protocol['end_ms'])]:
            for case,fee,slip in [('MODELED_COSTS','0.00055','0.0005'),('ZERO_COST_DIAGNOSTIC','0','0')]:
                result=replay(bars,decisions,rates if fee!='0' else {},marks,left,right,fee,slip)
                if abs(number(result['accounting_residual']))>number('.00000001'):raise ValueError('cash ledger does not reconcile')
                detailed=dict(arm=arm,period=period,cost_case=case,**result)
                (private/f'fixed-{arm}-{period}-{case}.json').write_text(json.dumps(detailed,indent=2)+'\n',encoding='utf-8')
                results.append({k:v for k,v in detailed.items() if k not in ['trades','entry_events','daily_closing_equity']})
    report={k:v for k,v in before.items() if k!='results'}
    report.update(results=results,current_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        engineering_fix='Peak-based drawdown halt and latched daily risk stop; identical bars, rules, parameters and costs',
        baseline_results_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest())
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


def run(output,private):
    output.mkdir(parents=True,exist_ok=True);private.mkdir(parents=True,exist_ok=True)
    protocol_file=output/'protocol.json'
    if protocol_file.exists():raise ValueError('experiment already registered; do not overwrite')
    end=int(time.time()*1000)//INTERVAL*INTERVAL;start=end-90*86400000
    protocol=dict(registered_ms=int(time.time()*1000),symbol='BTCUSDT',interval_ms=INTERVAL,
        start_ms=start,end_ms=end,warmup=240,split_ms=end-30*86400000,
        arms=ARMS,initial_equity='200',risk_fraction='0.01',max_notional_ratio='1',sl_atr='1.2',ttl_bars=96,
        daily_new_risk_halt='0.03',hard_drawdown_halt='0.10',request_budget=32,
        cost_cases=['MODELED_COSTS','ZERO_COST_DIAGNOSTIC'],
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scope='RETROSPECTIVE_EXPLORATION_NOT_INDEPENDENT_FORWARD_EVIDENCE',
        no_production_changes=True,no_account_orders=True,no_ai_calls=True)
    protocol_file.write_text(json.dumps(protocol,indent=2)+'\n',encoding='utf-8')
    capture=Capture(private,32)
    try:
        bars=capture.candles('/v5/market/kline',start-240*INTERVAL,end)
        marks=capture.candles('/v5/market/mark-price-kline',start-240*INTERVAL,end)
        mark_prices={b[0]:b[1] for b in marks}
        instrument=capture.get('/v5/market/instruments-info',dict(category='linear',symbol='BTCUSDT'))['list'][0]
        if instrument['symbol']!='BTCUSDT':raise ValueError('wrong instrument')
        funding_interval=int(instrument['fundingInterval'])*60000
        rates={};right=end-1
        for _ in range(4):
            rows=capture.get('/v5/market/funding/history',dict(category='linear',symbol='BTCUSDT',startTime=start,endTime=right,limit=200)).get('list',[])
            if not rows:break
            for row in rows:
                ts=int(row['fundingRateTimestamp']);rate=row['fundingRate']
                if ts in rates and rates[ts]!=rate:raise ValueError('funding conflict')
                rates[ts]=rate
            earliest=min(int(r['fundingRateTimestamp']) for r in rows)
            if earliest<=start or len(rows)<200:break
            if earliest>=right:raise ValueError('funding page stalled')
            right=earliest-1
        expected=set(range((start+funding_interval-1)//funding_interval*funding_interval,end,funding_interval))
        if expected!=set(rates):raise ValueError('funding schedule incomplete/changed; do not assume zero')
        dataset=dict(bars=bars,marks=marks,funding=rates)
        data_file=private/'dataset.json';data_file.write_text(json.dumps(dataset),encoding='utf-8')
        results=[]
        for arm in ARMS:
            decisions=signals(bars,arm)
            for period,left,right in [('first_60_days',start,protocol['split_ms']),('last_30_days',protocol['split_ms'],end)]:
                for cost_case,fee,slip in [('MODELED_COSTS','0.00055','0.0005'),('ZERO_COST_DIAGNOSTIC','0','0')]:
                    result=replay(bars,decisions,rates if fee!='0' else {},mark_prices,left,right,fee,slip)
                    detailed=dict(arm=arm,period=period,cost_case=cost_case,**result)
                    (private/f'{arm}-{period}-{cost_case}.json').write_text(json.dumps(detailed,indent=2)+'\n',encoding='utf-8')
                    results.append({k:v for k,v in detailed.items() if k not in ['trades','entry_events','daily_closing_equity']})
        report=dict(protocol=protocol,dataset_sha256=hashlib.sha256(data_file.read_bytes()).hexdigest(),
                    bars=len(bars),funding_events=len(rates),funding_interval_minutes=funding_interval//60000,
                    results=results,independent_forward_advantage_proven=False,selected_for_deployment=None,
                    limitations=['Modeled next-open fills, no queue/liquidity simulation','Funding uses public rate and mark-bar open',
                                 'Close-sampled drawdown and unknown intrabar delay','Historical data is not unseen future evidence'])
        (output/'results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        return report
    finally:
        (output/'capture-manifest.json').write_text(json.dumps(capture.requests,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--private',type=Path,required=True)
    parser.add_argument('--replay-baseline',type=Path)
    args=parser.parse_args();result=replay_cached(args.replay_baseline,args.private,args.output) if args.replay_baseline else run(args.output,args.private)
    print(json.dumps(dict(runs=len(result['results']),bars=result['bars'],funding_events=result['funding_events']),indent=2))
