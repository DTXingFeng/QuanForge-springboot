"""Frozen two-year economic-source comparison. Public Bybit GET only; no credentials.

Historical research, not a live strategy or matching engine. All arms retained.
Decimal accounting; close signals execute next open. No parameter optimisation.
"""
import argparse
import csv
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

DAY=86400000
HOUR=3600000
D=Decimal
ARMS=['cash','buy_hold','sma200','momentum63','funding_carry']
ALLOWED={'/v5/market/kline','/v5/market/mark-price-kline','/v5/market/funding/history',
         '/v5/market/instruments-info','/v5/market/tickers'}


def n(v): return D(str(v))
def s(v):
    result=format(n(v),'f').rstrip('0').rstrip('.') if '.' in format(n(v),'f') else format(n(v),'f')
    return '0' if result in ('','-0') else result
def dump(path,value):
    with Path(path).open('x',encoding='utf-8') as f: json.dump(value,f,indent=2,ensure_ascii=False)
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def floor_qty(value,step): return (value/n(step)).to_integral_value(rounding=ROUND_DOWN)*n(step)


def daily_signals(bars,arm):
    if arm not in ARMS: raise ValueError('unknown arm')
    output=[]
    for i,b in enumerate(bars):
        if arm=='buy_hold': flag=True
        elif arm=='sma200': flag=i>=199 and n(b[4])>sum(n(x[4]) for x in bars[i-199:i+1])/200
        elif arm=='momentum63': flag=i>=63 and n(b[4])>n(bars[i-63][4])
        else: flag=False
        output.append(flag)
    return output


def spot_replay(bars,signals,start,end,fee,slip,qty_step,min_qty,min_notional):
    cash=n(200);qty=n(0);fees=n(0);slippage=n(0);peak=n(200);dd=n(0)
    events=[];curve=[];invested=0;blocked=0
    for i,b in enumerate(bars):
        ts,o,h,low,c,_=b
        if not start<=ts<end: continue
        want=bool(signals[i-1]) if i else False
        if want and qty==0:
            fill=n(o)*(1+n(slip));q=floor_qty(cash/(fill*(1+n(fee))),qty_step)
            if q>0 and q>=n(min_qty) and q*fill>=n(min_notional):
                paid=q*fill*n(fee);cash-=q*fill+paid;qty=q;fees+=paid
                slippage+=q*(fill-n(o))
                events.append(dict(at=ts,signal_at=bars[i-1][0],side='BUY',price=s(fill),qty=s(q)))
            else: blocked+=1
        elif not want and qty:
            fill=n(o)*(1-n(slip));paid=qty*fill*n(fee);cash+=qty*fill-paid
            fees+=paid;slippage+=qty*(n(o)-fill)
            events.append(dict(at=ts,signal_at=bars[i-1][0],side='SELL',price=s(fill),qty=s(qty)))
            qty=n(0)
        if qty: invested+=1
        # Daily close liquidation value; sampled DD, not intraday maximum DD.
        nav=cash+qty*n(c)*(1-n(slip))*(1-n(fee))
        peak=max(peak,nav);dd=max(dd,1-nav/peak)
        curve.append(dict(at=ts+DAY,equity=s(nav)))
        if ts+DAY==end and qty:
            fill=n(c)*(1-n(slip));paid=qty*fill*n(fee)
            cash+=qty*fill-paid;fees+=paid;slippage+=qty*(n(c)-fill)
            events.append(dict(at=end,signal_at=None,side='SELL',price=s(fill),qty=s(qty),reason='PREDECLARED_TERMINAL_CLOSE'))
            qty=n(0)
    if not curve: raise ValueError('no period bars')
    if qty: raise ValueError('missing terminal bar')
    return dict(status='HISTORICAL_MODEL',initial_equity='200',final_equity=s(cash),
        net_pnl=s(cash-200),return_pct=s((cash/200-1)*100),daily_close_max_drawdown_pct=s(dd*100),
        fees=s(fees),slippage_diagnostic=s(slippage),orders=len(events),
        entries=sum(e['side']=='BUY' for e in events),invested_days=invested,
        blocked_minimum_days=blocked,events=events,curve=curve)


def carry(spot,perp,marks,rates,start,end,spot_fee,perp_fee,slip,qty_step,min_qty,min_notional):
    sp=[b for b in spot if start<=b[0]<end];pp={b[0]:b for b in perp if start<=b[0]<end}
    mm={b[0]:b for b in marks if start<=b[0]<end}
    if not sp or sp[-1][0]+DAY!=end or sp[0][0]!=start: raise ValueError('incomplete carry period')
    p0=n(pp[start][1]);s0=n(sp[0][1]);f=n(slip)
    sbuy=s0*(1+f);psell=p0*(1-f)
    # Reserve a full initial perpetual notional; both legs share total capital 200.
    q=floor_qty(n(200)/(sbuy*(1+n(spot_fee))+psell*(1+n(perp_fee))),qty_step)
    if q<=0 or q<n(min_qty) or min(q*sbuy,q*psell)<n(min_notional):
        return dict(status='BELOW_MINIMUM',return_pct=None,qty=s(q))
    entry_fees=q*(sbuy*n(spot_fee)+psell*n(perp_fee))
    reserve=n(200)-q*sbuy-entry_fees
    fund=n(0);min_reserve=reserve;minimum_ratio=None;failure=None;peak=n(200);dd=n(0);curve=[]
    funding_events={int(t):n(r) for t,r in rates.items() if start<int(t)<end}
    for ts in funding_events:
        if ts not in mm: raise ValueError('funding mark missing')
    # Evaluate short margin at each hour's high BEFORE crediting that hour's funding.
    # No automatic spot collateral transfer or portfolio-margin offset is assumed.
    day_fund={}
    for ts,b in sorted(mm.items()):
        worst=reserve+fund+q*(psell-n(b[2]))
        ratio=worst/(q*n(b[2]))
        if minimum_ratio is None or ratio<minimum_ratio: minimum_ratio=ratio
        min_reserve=min(min_reserve,worst)
        if worst<=0 and failure is None: failure=ts
        if ts in funding_events: fund+=q*n(b[1])*funding_events[ts]
        day_fund[ts//DAY]=fund
    for b in sp:
        ts=b[0];p=pp[ts];cumulative=day_fund.get(ts//DAY,n(0))
        sx=n(b[4])*(1-f);px=n(p[4])*(1+f)
        exit_fee=q*(sx*n(spot_fee)+px*n(perp_fee))
        nav=n(200)+q*((sx-sbuy)+(psell-px))+cumulative-entry_fees-exit_fee
        peak=max(peak,nav);dd=max(dd,1-nav/peak);curve.append(dict(at=ts+DAY,equity=s(nav)))
    s1=n(sp[-1][4]);p1=n(pp[sp[-1][0]][4]);ssell=s1*(1-f);pbuy=p1*(1+f)
    fees=entry_fees+q*(ssell*n(spot_fee)+pbuy*n(perp_fee))
    basis=q*((s1-s0)+(p0-p1));slippage=q*f*(s0+p0+s1+p1)
    net=basis-slippage+fund-fees
    # Counterfactual result is explicitly invalid as an executable return after margin exhaustion.
    return dict(status='RESERVE_EXHAUSTED' if failure is not None else 'HISTORICAL_MODEL',
        initial_equity='200',final_equity=s(200+net),net_pnl=s(net),
        return_pct=None if failure is not None else s(net/2),counterfactual_return_pct=s(net/2),
        daily_close_max_drawdown_pct=s(dd*100),fees=s(fees),slippage_diagnostic=s(slippage),
        basis_pnl_before_costs=s(basis),funding_income=s(fund),funding_events=len(funding_events),
        negative_funding_events=sum(r<0 for r in funding_events.values()),qty=s(q),orders=4,
        spot_notional_at_entry=s(q*s0),perp_notional_at_entry=s(q*p0),
        initial_perp_cash_reserve=s(reserve),minimum_hourly_short_reserve=s(min_reserve),
        minimum_hourly_short_equity_over_mark_notional=s(minimum_ratio) if minimum_ratio is not None else None,
        reserve_exhausted_at=failure,curve=curve)


class PublicCapture:
    def __init__(self,directory): self.directory=directory;self.calls=0
    def get(self,path,**params):
        if path not in ALLOWED or self.calls>=96: raise ValueError('public GET budget/allowlist')
        self.calls+=1
        url='https://api.bybit.com'+path+'?'+urllib.parse.urlencode(params)
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'QFS-economic-research/1'}),timeout=20) as response:
            raw=response.read()
        (self.directory/f'public-{self.calls:03}.json').write_bytes(raw)
        value=json.loads(raw)
        if value.get('retCode')!=0: raise ValueError(f'public API failure {value.get("retCode")}')
        print(json.dumps(dict(call=self.calls,path=path,symbol=params.get('symbol'))),flush=True)
        return value['result']
    def bars(self,path,start,end,interval,**params):
        found={};cursor=end-1;step=DAY if interval=='D' else HOUR
        while cursor>=start:
            raw=self.get(path,start=start,end=cursor,interval=interval,limit=1000,**params)['list']
            if not raw: raise ValueError('empty historical page')
            timestamps=[]
            for row in raw:
                ts=int(row[0]);timestamps.append(ts)
                if not start<=ts<end: continue
                b=[ts]+row[1:5]+[row[5] if len(row)>5 else '0']
                if ts in found and found[ts]!=b: raise ValueError('conflicting duplicate bar')
                if min(n(v) for v in b[1:5])<=0 or n(b[2])<max(n(b[1]),n(b[4])) or n(b[3])>min(n(b[1]),n(b[4])):
                    raise ValueError('invalid OHLC')
                found[ts]=b
            following=min(timestamps)-1
            if following>=cursor: raise ValueError('pagination did not advance')
            cursor=following
        if set(found)!=set(range(start,end,step)): raise ValueError('missing or unaligned bar')
        return [found[t] for t in sorted(found)]
    def funding(self,symbol,start,end):
        found={};cursor=end-1
        while cursor>=start:
            raw=self.get('/v5/market/funding/history',category='linear',symbol=symbol,
                         startTime=start,endTime=cursor,limit=200)['list']
            if not raw: break
            stamps=[]
            for row in raw:
                ts=int(row['fundingRateTimestamp']);stamps.append(ts)
                if start<=ts<end:
                    if ts in found and found[ts]!=row['fundingRate']: raise ValueError('conflicting funding duplicate')
                    found[ts]=row['fundingRate']
            following=min(stamps)-1
            if following>=cursor: raise ValueError('funding pagination did not advance')
            cursor=following
        return found


def register(directory):
    directory.mkdir(parents=True,exist_ok=True)
    end=int(time.time()*1000)//DAY*DAY
    protocol=dict(version=1,registered_utc=datetime.now(timezone.utc).isoformat(),
        source_sha256=sha(__file__),symbols=['BTCUSDT','ETHUSDT'],arms=ARMS,
        initial_capital_per_independent_run='200',start=end-730*DAY,end_exclusive=end,warmup_days=240,
        periods='two consecutive 365-day windows, each resets capital and positions',
        signal_execution='closed daily signal; following daily open; terminal close predeclared',
        costs=dict(spot_fee_per_side='0.001',perp_fee_per_side='0.00055',adverse_slippage_per_leg='0.0005'),
        cost_cases=['base','double_fees_and_slippage'],max_public_GET_attempts=96,
        constraints='present-day published instrument minimum/quantity steps applied to historical simulation',
        funding='actual historical settlement rate times that hour mark open, strictly inside holding period',
        margin='reserve full entry perp notional; hourly high before funding credit; no spot collateral offsets; no rebalancing',
        drawdown='daily close liquidation NAV; not intraday DD',
        selection='all 40 cases retained; no optimisation or automatic deployment')
    dump(directory/'protocol.json',protocol)
    return protocol


def capture(directory,p):
    client=PublicCapture(directory);data={}
    for symbol in p['symbols']:
        entry={}
        for category in ('spot','linear'):
            entry[category+'_instrument']=client.get('/v5/market/instruments-info',category=category,symbol=symbol)['list'][0]
            entry[category]=client.bars('/v5/market/kline',p['start']-240*DAY,p['end_exclusive'],'D',category=category,symbol=symbol)
        entry['marks']=client.bars('/v5/market/mark-price-kline',p['start'],p['end_exclusive'],'60',category='linear',symbol=symbol)
        entry['funding']=client.funding(symbol,p['start'],p['end_exclusive'])
        interval=int(entry['linear_instrument']['fundingInterval'])*60000
        expected=set(range(p['start'],p['end_exclusive'],interval))
        if set(entry['funding'])!=expected:
            raise ValueError('funding coverage differs from constant current schedule; do not assume zero or hide schedule changes')
        entry['ticker_snapshot']=client.get('/v5/market/tickers',category='linear',symbol=symbol)['list'][0]
        entry['funding_coverage']=dict(count=len(expected),assumed_constant_interval_ms=interval,missing=0)
        data[symbol]=entry
    dump(directory/'dataset.json',data)
    dump(directory/'capture-manifest.json',dict(public_GET_calls=client.calls,dataset_sha256=sha(directory/'dataset.json'),
        raw_files=[dict(file=f.name,sha256=sha(f)) for f in sorted(directory.glob('public-*.json'))]))
    return data


def evaluate(data,p):
    results=[]
    for symbol,entry in data.items():
        spotlot=entry['spot_instrument']['lotSizeFilter'];perplot=entry['linear_instrument']['lotSizeFilter']
        step=spotlot['basePrecision'];perpstep=perplot['qtyStep']
        common=max(n(step),n(perpstep))
        if common/min(n(step),n(perpstep))%1: raise ValueError('incompatible lot steps')
        for year in (0,1):
            start=p['start']+year*365*DAY;end=start+365*DAY
            for case,multiple in [('base',1),('double_fees_and_slippage',2)]:
                sf=n(p['costs']['spot_fee_per_side'])*multiple;pf=n(p['costs']['perp_fee_per_side'])*multiple
                slip=n(p['costs']['adverse_slippage_per_leg'])*multiple
                for arm in p['arms']:
                    if arm=='funding_carry':
                        r=carry(entry['spot'],entry['linear'],entry['marks'],entry['funding'],start,end,
                            sf,pf,slip,common,max(n(spotlot['minOrderQty']),n(perplot['minOrderQty'])),
                            max(n(spotlot['minOrderAmt']),n(perplot['minNotionalValue'])))
                    else:
                        r=spot_replay(entry['spot'],daily_signals(entry['spot'],arm),start,end,sf,slip,
                            step,spotlot['minOrderQty'],spotlot['minOrderAmt'])
                    results.append(dict(symbol=symbol,period=year+1,start=start,end_exclusive=end,cost_case=case,arm=arm,**r))
    return dict(protocol_source_sha256=p['source_sha256'],evaluator_source_sha256=sha(__file__),runs=results)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['capture','replay'])
    parser.add_argument('--directory',type=Path,required=True);args=parser.parse_args();directory=args.directory
    if args.action=='capture':
        p=register(directory);data=capture(directory,p)
    else:
        p=json.loads((directory/'protocol.json').read_text(encoding='utf-8'))
        data=json.loads((directory/'dataset.json').read_text(encoding='utf-8'))
        manifest=json.loads((directory/'capture-manifest.json').read_text(encoding='utf-8'))
        if sha(directory/'dataset.json')!=manifest['dataset_sha256']: raise ValueError('dataset hash mismatch')
        if sha(__file__)!=p['source_sha256']: raise ValueError('registered source changed; preserve and register a new version')
    r=evaluate(data,p);dump(directory/'results.json',r)
    columns=['symbol','period','cost_case','arm','status','return_pct','counterfactual_return_pct',
        'daily_close_max_drawdown_pct','orders','fees','funding_income','basis_pnl_before_costs',
        'slippage_diagnostic','minimum_hourly_short_equity_over_mark_notional','reserve_exhausted_at']
    with (directory/'comparison.csv').open('x',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(r['runs'])
    print(json.dumps(dict(runs=len(r['runs']),results=str(directory/'results.json'))),flush=True)


if __name__=='__main__': main()
