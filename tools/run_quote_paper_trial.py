"""One-hour bounded, local-only quote PAPER worker. Public HTTP + readonly SSH.

run starts/resumes the same frozen SQLite experiment. status is readonly.
No account API, AI inference request, exchange order, service deployment or timer.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from contextlib import contextmanager
from quote_paper_trial import Trial,n

ENDPOINTS={'/v5/market/time','/v5/market/tickers','/v5/market/instruments-info','/v5/market/risk-limit'}


class Public:
    def __init__(self,directory):
        self.directory=directory
        counter=directory/'request-counter.json'
        self.count=int(json.loads(counter.read_text())['attempts']) if counter.exists() else max(
            [int(p.stem.split('-')[-1]) for p in directory.glob('public-*.json')],default=0)
    def get(self,path,**params):
        if path not in ENDPOINTS or self.count>=1000: raise ValueError('public request allowlist/budget')
        self.count+=1
        counter=self.directory/'request-counter.tmp';counter.write_text(json.dumps(dict(attempts=self.count)))
        os.replace(counter,self.directory/'request-counter.json')
        url='https://api.bybit.com'+path+'?'+urllib.parse.urlencode(params)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url,timeout=12) as response: raw=response.read()
        with (self.directory/f'public-{self.count:04}.json').open('xb') as f: f.write(raw)
        value=json.loads(raw)
        if value.get('retCode')!=0: raise ValueError('public market rejected')
        return value
    def clock(self):
        before=int(time.time()*1000);result=self.get('/v5/market/time');after=int(time.time()*1000)
        server=int(result['result']['timeNano'])//1000000
        uncertainty=(after-before+1)//2;offset=server-(before+after)//2
        if after<before or uncertainty>1000 or abs(offset)>5000: raise ValueError('clock outside bounds')
        return dict(offset=offset,uncertainty=uncertainty,calibrated_at=after)


def feed(after):
    script='''import sqlite3,json,time
c=sqlite3.connect('file:/mnt/nvme/quanforge/data/quanforge.db?mode=ro',uri=True);c.row_factory=sqlite3.Row
rows=[dict(r) for r in c.execute("select id,symbol,action,entry,stop_loss,take_profit,created_at,sys_version,exec_mode from ai_advice_track where id>? and exec_mode='PAPER' order by id limit 50",(AFTER,))]
print(json.dumps(dict(max_id=c.execute('select coalesce(max(id),0) from ai_advice_track').fetchone()[0],rows=rows,source_at=int(time.time()*1000))))
'''.replace('AFTER',str(int(after)))
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','xingfeng@192.168.8.240','python3','-'],
        input=script.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=True)
    return json.loads(result.stdout)


def instrument(client,symbol):
    info=client.get('/v5/market/instruments-info',category='linear',symbol=symbol)['result']['list'][0]
    if info['symbol']!=symbol or info['status']!='Trading': raise ValueError('wrong/inactive instrument')
    tiers=client.get('/v5/market/risk-limit',category='linear',symbol=symbol)['result']['list']
    tier=min(tiers,key=lambda t:n(t['riskLimitValue']));lot=info['lotSizeFilter']
    return dict(qty_step=lot['qtyStep'],min_qty=lot['minOrderQty'],min_notional=lot['minNotionalValue'],
        tick_size=info['priceFilter']['tickSize'],max_leverage=info['leverageFilter']['maxLeverage'],maintenance=str(tier['maintenanceMargin']))


@contextmanager
def writer_lock(path):
    with path.open('a+b') as f:
        if path.stat().st_size==0: f.write(b'0');f.flush()
        f.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try: yield
        finally:
            f.seek(0)
            if os.name=='nt': msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(f,fcntl.LOCK_UN)


def snapshot(trial,directory):
    value=trial.report();value['worker_pid']=os.getpid()
    temp=directory/'report.tmp';temp.write_text(json.dumps(value,indent=2),encoding='utf-8')
    os.replace(temp,directory/'report.json')
    return value


def run(directory):
    directory.mkdir(parents=True,exist_ok=True)
    with writer_lock(directory/'writer.lock'):
        client=Public(directory);clock=None
        for _ in range(2):
            try: clock=client.clock();break
            except Exception:
                if client.count>=2: raise
        def now(): return int(time.time()*1000)+clock['offset']+clock['uncertainty']
        protocol=directory/'protocol.json'
        if protocol.exists(): seed=json.loads(protocol.read_text(encoding='utf-8'))
        else:
            initial=feed(0);start=now()
            seed=dict(start=start,watermark=initial['max_id'],end_at=start+3600000,entry_cutoff=start+3000000,
                source='read-only current QF-S PAPER feed',duration_minutes=60,max_polls=720,poll_seconds=5,
                worker_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),clock=clock)
            with protocol.open('x',encoding='utf-8') as f: json.dump(seed,f,indent=2)
        if seed['worker_source_sha256']!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(): raise ValueError('frozen worker changed')
        t=Trial(directory/'trial.sqlite',seed);last_feed=0;quotes={};lots={};last_notice=0
        print(json.dumps(dict(started=True,pid=os.getpid(),seed=seed)),flush=True)
        try:
            if t.state['ended']:
                snapshot(t,directory);print(json.dumps(dict(ended=True,resumed=False)),flush=True);return
            for poll in range(seed['max_polls']):
                if now()>=seed['end_at'] or t.state['ended']: break
                if now()>=seed['entry_cutoff']:
                    with t.atomic(): t.state['entry_disabled']=True;t.state['pending']=None
                if int(time.time()*1000)-clock['calibrated_at']>600000:
                    try: clock=client.clock()
                    except Exception as e: t.error(now(),'clock',e)
                if now()-last_feed>=30000:
                    try:
                        source=feed(t.state['watermark'])
                        for signal in source['rows']:
                            at=now()
                            if signal['created_at']<seed['start'] or at-signal['created_at']>90000:
                                t.reject_source(signal,at,'STALE_OR_PRE_REGISTRATION');continue
                            if t.state['entry_disabled']:
                                t.reject_source(signal,at,'ENTRY_DISABLED');continue
                            try:
                                symbol=signal['symbol']
                                if symbol not in lots: lots[symbol]=instrument(client,symbol)
                                t.offer(signal,lots[symbol],now())
                            except Exception as e:
                                t.error(now(),'signal-metadata',e);t.reject_source(signal,now(),'SIGNAL_OR_METADATA_UNAVAILABLE')
                    except Exception as e: t.error(now(),'source-feed',e)
                    last_feed=now()
                symbols={a['position']['symbol'] for a in t.state['arms'].values() if a['position']}
                if t.state['pending']: symbols.add(t.state['pending']['signal']['symbol'])
                if not symbols: symbols={'XRPUSDT'}
                for symbol in symbols:
                    try:
                        result=client.get('/v5/market/tickers',category='linear',symbol=symbol);r=result['result']['list'][0]
                        if r['symbol']!=symbol: raise ValueError('wrong quote symbol')
                        q=dict(symbol=symbol,at=int(result['time']),bid=r['bid1Price'],ask=r['ask1Price'],
                            mark=r['markPrice'],bid_size=r['bid1Size'],ask_size=r['ask1Size'],next_funding=int(r['nextFundingTime']))
                        t.quote(q,now());quotes[symbol]=q
                    except Exception as e: t.error(now(),'quote',e)
                report=snapshot(t,directory)
                if now()-last_notice>=60000:
                    print(json.dumps(dict(at=now(),poll=poll,counts=report['counts'],accounting=report['accounting'])),flush=True);last_notice=now()
                time.sleep(seed['poll_seconds'])
            t.finish(quotes,now());snapshot(t,directory)
            print(json.dumps(dict(ended=True,counts=t.report()['counts'])),flush=True)
        finally: t.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['run','status'])
    parser.add_argument('--directory',type=Path,required=True);args=parser.parse_args()
    if args.action=='run': run(args.directory)
    else:
        c=sqlite3.connect((args.directory/'trial.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
        state=json.loads(c.execute('select payload from state where id=1').fetchone()[0])
        print(json.dumps(dict(state=state,counts=dict(c.execute('select kind,count(*) from events group by kind'))),indent=2));c.close()


if __name__=='__main__': main()
