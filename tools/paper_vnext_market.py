"""Public Bybit market adapter with persisted request budget and raw receipts."""
import gzip
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

ALLOWED={'/v5/market/time','/v5/market/kline','/v5/market/tickers','/v5/market/instruments-info',
         '/v5/market/risk-limit','/v5/market/funding/history','/v5/market/mark-price-kline'}


def atomic_json(path,value):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    os.replace(temp,path)


class Market:
    def __init__(self,root,proxy=None,budget=20000):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.proxy=proxy;self.budget=budget;self.counter_path=self.root/'request-budget.json';self.last_receipt=None
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy} if proxy else {}))
    def get(self,path,**params):
        if path not in ALLOWED: raise ValueError('only allowlisted public market GET')
        day=int(time.time())//86400
        counter=json.loads(self.counter_path.read_text()) if self.counter_path.exists() else dict(day=day,attempts=0,total=0)
        if counter['day']!=day: counter.update(day=day,attempts=0)
        if counter['attempts']>=self.budget: raise ValueError('daily public request budget exhausted')
        counter['attempts']+=1;counter['total']+=1;atomic_json(self.counter_path,counter)
        before=int(time.time()*1000);record=dict(id=f'{day}:{counter["total"]}',path=path,params=params,started=before)
        try:
            url='https://api.bybit.com'+path+'?'+urllib.parse.urlencode(sorted(params.items()))
            with self.opener.open(url,timeout=5) as response: raw=response.read()
            value=json.loads(raw);record.update(ended=int(time.time()*1000),raw_utf8=raw.decode(),sha256=hashlib.sha256(raw).hexdigest())
            if value.get('retCode')!=0: raise ValueError('public API rejected: '+str(value.get('retCode')))
            record['status']='OK';self.last_receipt=record['id'];return value
        except Exception as e:
            record.update(status='FAILED',ended=int(time.time()*1000),error_type=type(e).__name__);raise
        finally:
            with gzip.open(self.root/f'public-{day}-{before//3600000%24:02}.jsonl.gz','ab') as f:
                f.write((json.dumps(record,ensure_ascii=True)+'\n').encode())
    def calibrate(self):
        before=int(time.time()*1000);value=self.get('/v5/market/time');after=int(time.time()*1000)
        server=int(value['result']['timeNano'])//1000000;uncertainty=(after-before+1)//2
        offset=server-(before+after)//2
        if after<before or uncertainty>1000 or abs(offset)>5000: raise ValueError('clock calibration outside bounds')
        return dict(offset=offset,uncertainty=uncertainty,local_at=after)
    def instrument(self,symbol):
        value=self.get('/v5/market/instruments-info',category='linear',symbol=symbol)['result']['list'][0]
        if value['symbol']!=symbol or value['status']!='Trading' or value.get('contractType')!='LinearPerpetual':
            raise ValueError('not a trading linear perpetual')
        tiers=self.get('/v5/market/risk-limit',category='linear',symbol=symbol)['result']['list']
        tier=min(tiers,key=lambda t:float(t['riskLimitValue']));lot=value['lotSizeFilter']
        return dict(qty_step=lot['qtyStep'],min_qty=lot['minOrderQty'],min_notional=lot['minNotionalValue'],
            tick_size=value['priceFilter']['tickSize'],max_leverage=value['leverageFilter']['maxLeverage'],
            maintenance=str(tier['maintenanceMargin']),funding_interval_ms=int(value['fundingInterval'])*60000)
    def quote(self,symbol):
        value=self.get('/v5/market/tickers',category='linear',symbol=symbol);r=value['result']['list'][0]
        if r['symbol']!=symbol: raise ValueError('wrong quote symbol')
        return dict(symbol=symbol,at=int(value['time']),bid=r['bid1Price'],ask=r['ask1Price'],mark=r['markPrice'],
            bid_size=r['bid1Size'],ask_size=r['ask1Size'],next_funding=int(r['nextFundingTime']),receipt=self.last_receipt)
    def bars(self,symbol,end=None,limit=1000):
        params=dict(category='linear',symbol=symbol,interval='5',limit=limit)
        if end is not None: params['end']=end
        value=self.get('/v5/market/kline',**params)
        return [[int(b[0])]+[float(x) for x in b[1:6]] for b in value['result']['list']]
    def funding(self,symbol,at):
        rows=self.get('/v5/market/funding/history',category='linear',symbol=symbol,startTime=at,endTime=at,limit=1)['result']['list']
        if len(rows)!=1 or int(rows[0]['fundingRateTimestamp'])!=at: raise ValueError('settled funding not available yet')
        bars=self.get('/v5/market/mark-price-kline',category='linear',symbol=symbol,interval='1',start=at,end=at+59999,limit=1)['result']['list']
        if len(bars)!=1 or int(bars[0][0])!=at: raise ValueError('settlement-minute mark missing')
        return rows[0]['fundingRate'],bars[0][1]
