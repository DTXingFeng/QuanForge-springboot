"""Bounded forward PAPER polling. Only public market GET URLs, no account/order API.

Default is one poll; no unattended process is installed. The SQLite file is new
research evidence, never a production trading database. Offline input is labeled
engineering replay; its PnL must not be promoted into forward performance.
"""
import argparse
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from verified_paper import Ledger, Paper, canonical

HOST='https://api.bybit.com'
ALLOWED={'/v5/market/kline','/v5/market/tickers','/v5/market/time'}


def public_get(endpoint, params):
    if endpoint not in ALLOWED:
        raise ValueError('market GET endpoints only')
    url=HOST+endpoint+'?'+urllib.parse.urlencode(params)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url,timeout=15) as response:
        result=json.load(response)
    if result.get('retCode')!=0:
        raise ValueError('public market API rejected')
    return result


def fetch_bars(config, cursor, now):
    # At most four pages. Stop rather than fabricate a large missing interval.
    by_time={}; end=None
    target=min(cursor if cursor is not None else now, now-config['warmup']*config['interval_ms'])
    for _ in range(4):
        params=dict(category='linear',symbol=config['symbol'],interval=config['interval_ms']//60000,limit=1000)
        if end is not None:params['end']=end
        response=public_get('/v5/market/kline',params)
        raw=response['result'].get('list',[])
        if not raw:break
        for row in raw:
            bar=(int(row[0]),*[float(x) for x in row[1:6]])
            if bar[0] in by_time and by_time[bar[0]]!=bar:raise ValueError('conflicting REST pages')
            by_time[bar[0]]=bar
        earliest=min(int(row[0]) for row in raw)
        if earliest<=target:break
        if end is not None and earliest>=end:raise ValueError('pagination made no progress')
        end=earliest-1
    return list(by_time.values())


def calibrate_clock():
    """Independent server-clock sample, never infer freshness from the quote itself.

    Keep the RTT uncertainty interval. Reject large skew/slow calibration instead
    of accepting old quotes by moving the observation clock to their timestamp.
    """
    before=int(time.time()*1000)
    response=public_get('/v5/market/time',{})
    after=int(time.time()*1000)
    server=int(response['result']['timeNano'])//1000000
    uncertainty=(after-before+1)//2
    offset=server-(before+after)//2
    if after<before or uncertainty>1000 or abs(offset)>5000:
        raise ValueError('clock calibration outside allowed skew/RTT')
    return dict(offset_ms=offset,uncertainty_ms=uncertainty,local_at=after,server_at=server)


def run(args):
    config=json.loads(args.config.read_text(encoding='utf-8'))
    sources=[Path(__file__),Path(__file__).with_name('verified_paper.py')]
    config['implementation_hash']=hashlib.sha256(b''.join(p.read_bytes() for p in sources)).hexdigest()
    args.db.parent.mkdir(parents=True,exist_ok=True)
    clock=calibrate_clock()
    ledger=Ledger(args.db)
    def clock_now(upper=True):
        return int(time.time()*1000)+clock['offset_ms']+(clock['uncertainty_ms'] if upper else -clock['uncertainty_ms'])
    now=clock_now()
    engine=Paper(ledger,config,now)
    with ledger.db:
        ledger.append('clock:'+str(clock['local_at']),'CLOCK_CALIBRATION',now,clock)
    errors=[]
    try:
        for poll in range(args.polls):
            # Existing exposure can still be marked/stopped even if bar ingestion fails.
            # Signals created from bars are consumed only by a fresh observed quote below.
            try:
                response=public_get('/v5/market/tickers',dict(category='linear',symbol=config['symbol']))
                observed=clock_now()
                row=response['result']['list'][0]
                if row['symbol']!=config['symbol']:raise ValueError('wrong quote symbol')
                engine.observe_quote(row['lastPrice'],int(response['time']),observed)
            except Exception as error:
                errors.append(dict(stage='quote',type=type(error).__name__,at=int(time.time()*1000)))
            try:
                now=clock_now(False)
                raw=fetch_bars(config,engine.state['cursor'],now)
                engine.process(raw,clock_now(False))
            except Exception as error:
                errors.append(dict(stage='bars',type=type(error).__name__,at=int(time.time()*1000)))
            if poll+1<args.polls:time.sleep(args.poll_seconds)
        with ledger.db:
            for i,error in enumerate(errors):
                ledger.append('error:'+str(error['at'])+':'+str(i),'POLL_ERROR',error['at'],error)
        result=engine.report()
        result.update(poll_errors=errors,polls_requested=args.polls,background_process_installed=False,
                      clock_calibration=clock,observation_clock='independent server clock with RTT bounds',
                      strategy_advantage='NOT_ESTABLISHED',config=config,
                      note='Synthetic fills and costs; funding unknown; no exchange orders.')
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2))
        return 0 if not errors else 2
    finally:ledger.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--polls',type=int,default=1)
    parser.add_argument('--poll-seconds',type=int,default=60)
    args=parser.parse_args()
    if not 1<=args.polls<=120 or not 5<=args.poll_seconds<=60:
        parser.error('bounded runs only: polls 1..120, seconds 5..60')
    raise SystemExit(run(args))
