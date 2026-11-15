"""Frozen causal rules shared by offline research and the deployed PAPER worker."""
import hashlib
import json
import math
from bisect import bisect_right

INTERVAL=300000
HOUR=3600000
POLICIES=('trend','reversion','selector','cash')
VERSION='paperlab-5.1-20261115'


def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def ema(values,period):
    value=values[0]
    for x in values[1:]: value+=(x-value)*2/(period+1)
    return value
def atr(bars,period=14):
    values=[max(b[2]-b[3],abs(b[2]-a[4]),abs(b[3]-a[4])) for a,b in zip(bars,bars[1:])]
    return sum(values[-period:])/period


def closed_bars(rows,asof,limit=3000):
    unique={}
    for row in rows:
        ts=row[0]
        if not isinstance(ts,int) or ts%INTERVAL: raise ValueError('unaligned bar')
        if ts+INTERVAL>asof: continue
        b=[ts]+[float(x) for x in row[1:6]]
        if len(b)!=6 or not all(math.isfinite(x) for x in b) or min(b[1:5])<=0 or b[5]<0:
            raise ValueError('invalid bar')
        if b[2]<max(b[1],b[3],b[4]) or b[3]>min(b[1],b[2],b[4]): raise ValueError('invalid OHLC')
        if ts in unique and b!=unique[ts]: raise ValueError('conflicting duplicate')
        unique[ts]=b
    bars=[unique[t] for t in sorted(unique)]
    if limit is not None: bars=bars[-limit:]
    if any(b[0]-a[0]!=INTERVAL for a,b in zip(bars,bars[1:])): raise ValueError('missing closed bar')
    return bars


def hourly(bars,asof,limit=240):
    groups={}
    for b in bars: groups.setdefault(b[0]//HOUR*HOUR,[]).append(b)
    result=[]
    for ts,group in sorted(groups.items()):
        if ts+HOUR>asof or [b[0] for b in group]!=list(range(ts,ts+HOUR,INTERVAL)): continue
        result.append([ts,group[0][1],max(b[2] for b in group),min(b[3] for b in group),group[-1][4],sum(b[5] for b in group)])
    return result[-limit:] if limit is not None else result


def hour_metrics(hours):
    hours=hours[-240:]
    if len(hours)<120: return None
    hc=[b[4] for b in hours];fast=ema(hc,20);slow=ema(hc,60)
    previous=ema(hc[:-1],20);vol=atr(hours)
    strength=abs(fast-slow)/vol if vol>0 else 0
    direction='UP' if fast>slow and fast>previous else 'DOWN' if fast<slow and fast<previous else 'FLAT'
    return dict(strength=strength,direction=direction,hourly_ema20=fast,hourly_ema60=slow,
        regime='TREND' if strength>=.5 and direction!='FLAT' else 'RANGE')


def features(bars,metrics,asof,input_hash):
    base=dict(action=None,reason='WARMUP',asof=asof,input_hash=input_hash,version=VERSION,regime='WARMUP')
    if metrics is None or len(bars)<240: return base
    if asof-(bars[-1][0]+INTERVAL)>60000: return {**base,'reason':'STALE_BARS'}
    closes=[b[4] for b in bars[-241:]];previous=bars[-13:-1]
    return dict(**base,metrics=metrics,atr5=atr(bars[-15:]),reference=closes[-1],previous_close=closes[-2],
        ema5=ema(closes[-240:],20),prior_ema5=ema(closes[-241:-1],20),
        range_high=max(b[2] for b in previous),range_low=min(b[3] for b in previous),
        current_high=bars[-1][2],current_low=bars[-1][3],bar_close_at=bars[-1][0]+INTERVAL)


def evaluate(frame,policy='selector',roundtrip_cost=.0022):
    if policy not in POLICIES: raise ValueError('unknown policy')
    result={k:v for k,v in frame.items() if k!='metrics'};result['policy']=policy
    if 'metrics' not in frame: return result
    result.update(frame['metrics']);result['reason']='NO_SETUP'
    regime=result['regime'];direction=result['direction'];close=result['reference'];bar_atr=result['atr5']
    selected=('trend' if regime=='TREND' else 'reversion') if policy=='selector' else policy
    if selected=='cash': return {**result,'reason':'CASH_BASELINE'}
    distance=max(bar_atr*1.5,close*roundtrip_cost*2)
    if distance<=0: return result
    side=None;target=None
    if selected=='trend':
        if direction=='UP' and frame['previous_close']<=frame['prior_ema5'] and close>frame['ema5']: side='BUY'
        elif direction=='DOWN' and frame['previous_close']>=frame['prior_ema5'] and close<frame['ema5']: side='SELL'
        if side: target=close+(2*distance if side=='BUY' else -2*distance)
    elif selected=='reversion' and regime=='RANGE':
        high=frame['range_high'];low=frame['range_low'];mid=(high+low)/2
        if frame['current_high']>high and mid<close<high:
            side='SELL';distance=max(distance,frame['current_high']+bar_atr*.1-close);target=mid
        elif frame['current_low']<low and low<close<mid:
            side='BUY';distance=max(distance,close-frame['current_low']+bar_atr*.1);target=mid
    if side:
        reward=abs(target-close)
        if reward<distance*1.5 or reward<close*roundtrip_cost*3:
            return {**result,'reason':'REWARD_BELOW_COST_HURDLE','selected':selected}
        result.update(action=side,stop=close-distance if side=='BUY' else close+distance,target=target,
            initial_distance=distance,selected=selected,reason='TREND_RECLAIM' if selected=='trend' else 'FAILED_BREAKOUT')
    return result


def decide(rows,asof,policy='selector',roundtrip_cost=.0022):
    bars=closed_bars(rows,asof);hours=hourly(bars,asof)
    digest=hashlib.sha256(canonical([bars[-241:],hours]).encode()).hexdigest()
    return evaluate(features(bars,hour_metrics(hours),asof,digest),policy,roundtrip_cost)


def feature_series(rows,end):
    """Cached retrospective feature extraction; every frame uses only closed past data.

    History receipts use a causal rolling hash. Rule outputs match decide(); the
    receipt hash differs from the live rolling-window hash and does not enter rules.
    """
    bars=closed_bars(rows,end,limit=None);hours=hourly(bars,end,limit=None)
    ends=[b[0]+HOUR for b in hours];cache={};digest=b'';output=[]
    for i,b in enumerate(bars):
        asof=b[0]+INTERVAL;count=bisect_right(ends,asof)
        if count not in cache: cache[count]=hour_metrics(hours[max(0,count-240):count])
        digest=hashlib.sha256(digest+canonical(b).encode()).digest()
        output.append(features(bars[max(0,i-240):i+1],cache[count],asof,digest.hex()))
    return bars,output
