"""Production PAPER-only daemon: no credential, AI or exchange-order interface."""
import argparse
import hashlib
import json
import os
import signal
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from paper_vnext_strategy import decide,closed_bars,INTERVAL,VERSION,canonical
from paper_vnext_ledger import PaperBook
from paper_vnext_market import Market,atomic_json


@contextmanager
def lock(path):
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


def save_bars(book,rows,asof):
    bars=closed_bars(rows,asof)
    with book.atomic():
        for b in bars:
            encoded=canonical(b);old=book.db.execute('select payload from market_bars where at=?',(b[0],)).fetchone()
            if old and old[0]!=encoded: raise ValueError('previous closed market bar revised')
            book.db.execute('insert or ignore into market_bars values(?,?)',(b[0],encoded))


def report(book,root,health,quote=None):
    raw=book.report();state=book.state
    now=int(time.time()*1000)
    primary=state['arms']['profit_protect'];control=state['arms']['source_exit']
    rows=[json.loads(r[0]) for r in book.db.execute("select payload from events where kind='EQUITY' order by at desc limit 288")][::-1]
    recent=[dict(kind=k,at=at,payload=json.loads(p)) for k,at,p in book.db.execute(
        "select kind,at,payload from events where kind not in ('QUOTE','EQUITY','FRAME') order by at desc limit 24")]
    value=dict(version=VERSION,mode='PAPER_ONLY',heartbeat=now,worker_pid=os.getpid(),symbol='XRPUSDT',
        stage='HALTED' if state['risk_halt'] or state['day_halt'] else 'PAUSED' if state['manual_pause'] else 'RECOVERING' if state['funding_pending'] else health['stage'],
        capital='20',rules=raw['rules'],primary=primary,control=control,accounting=raw['accounting'],
        pending=state['pending'],risk_halt=state['risk_halt'],day_halt=state['day_halt'],manual_pause=state['manual_pause'],
        last_control=state['last_control'],funding_pending=len(state['funding_pending']),regime=state['regime'],
        quote=quote,health=health,equity_curve=rows,events=recent,counts=raw['counts'],started_at=state['seed']['start'],
        strategy=dict(name='行情状态切换',policy='selector',paper_passed=False,status='EXPERIMENTAL',
            mechanisms=['趋势回踩','突破失败回归'],validation='未通过持续纸面盈利验证'),
        performance_basis='Observed-quote PAPER with assumed fees/slippage and modeled settled funding; no exchange executions',
        real_order_capability=False)
    # Limit the public report; full immutable trade history remains in SQLite.
    value['primary']={**primary,'trades':primary['trades'][-50:]}
    value['control']={**control,'trades':control['trades'][-50:]}
    atomic_json(root/'report.json',value);return value


def run(root,proxy=None,max_polls=None):
    root.mkdir(parents=True,exist_ok=True)
    with lock(root/'worker.lock'):
        market=Market(root/'market-receipts',proxy)
        clock=market.calibrate()
        def now(upper=True):return int(time.time()*1000)+clock['offset']+(clock['uncertainty'] if upper else -clock['uncertainty'])
        metadata_path=root/'run.json'
        sources={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in
            ['paper_vnext_worker.py','paper_vnext_strategy.py','paper_vnext_ledger.py','paper_vnext_market.py']}
        if metadata_path.exists():
            metadata=json.loads(metadata_path.read_text())
            if metadata['sources']!=sources: raise ValueError('frozen paper release changed; preserve ledger before starting a new experiment')
            seed=metadata['seed'];lot=metadata['instrument']
        else:
            lot=market.instrument('XRPUSDT');start=now()
            seed=dict(start=start,watermark=start//INTERVAL,policy='selector',version=VERSION)
            metadata=dict(seed=seed,instrument=lot,sources=sources);atomic_json(metadata_path,metadata)
        book=PaperBook(root/'paper.sqlite',seed)
        book.db.execute('create table if not exists market_bars(at integer primary key,payload text not null)')
        book.db.commit();running=True
        def shutdown(*_):
            nonlocal running
            running=False
        signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
        health=dict(stage='WARMUP',errors=0,consecutive_errors=0,last_error=None,bar_count=0,last_quote_at=None,data_ok=False,
            clock=clock,engine_version=VERSION,paper_database='paper.sqlite')
        quote=None;backfill_end=None;last_bar_fetch=0;last_equity=0;last_notice=0;fund_retry_at=0;poll=0;recovery_pages=0
        report(book,root,health)
        try:
            while running and (max_polls is None or poll<max_polls):
                poll+=1;successful_quote=False
                try:
                    quote=market.quote('XRPUSDT');book.quote(quote,now());successful_quote=True
                    health.update(last_quote_at=quote['at'],consecutive_errors=0)
                except Exception as e:
                    health.update(errors=health['errors']+1,consecutive_errors=health['consecutive_errors']+1,last_error=type(e).__name__)
                    book.error(now(),'quote',e)
                command=root/'control.json'
                if command.exists():
                    try:
                        value=json.loads(command.read_text());book.control(value['id'],value['action'],now())
                    except Exception as e: book.error(now(),'control',e)
                count=book.db.execute('select count(*) from market_bars').fetchone()[0]
                # Risk quotes precede every bounded historical page; no bulk blocking recovery.
                if now()-last_bar_fetch>=15000 and successful_quote:
                    try:
                        recovering=book.state['cursor'] is not None and now()-book.state['cursor']>INTERVAL*4
                        raw=market.bars('XRPUSDT',end=backfill_end,limit=1000 if count<3000 or backfill_end is not None or recovering else 5)
                        save_bars(book,raw,now(False));last_bar_fetch=now()
                        if count<3000:
                            backfill_end=min(b[0] for b in raw)-1
                            count=book.db.execute('select count(*) from market_bars').fetchone()[0]
                            if count>=3000: backfill_end=None
                        else:
                            if book.state['cursor'] is not None and min(b[0] for b in raw)>book.state['cursor']+INTERVAL:
                                recovery_pages+=1
                                if recovery_pages>4: raise RuntimeError('historical recovery page budget exhausted')
                                backfill_end=min(b[0] for b in raw)-1;health.update(stage='RECOVERING',data_ok=False)
                                continue
                            backfill_end=None;recovery_pages=0
                            bars=[json.loads(r[0]) for r in book.db.execute('select payload from market_bars order by at desc limit 3000')][::-1]
                            bars=closed_bars(bars,now(False));health['data_ok']=True
                            if book.state['cursor'] is None:
                                with book.atomic():book.state['cursor']=bars[-1][0]
                            elif bars[-1][0]>book.state['cursor']:
                                decision=decide(bars,now(False),'selector');asof=decision.get('bar_close_at',bars[-1][0]+INTERVAL)
                                with book.atomic():
                                    if bars[-1][0]-book.state['cursor']>INTERVAL:
                                        book.emit('CATCH_UP',f'catchup:{asof}',now(),dict(previous_cursor=book.state['cursor'],last_bar=bars[-1][0],retrospective_fills=False))
                                    book.state['cursor']=bars[-1][0];book.state['regime']=decision
                                    book.emit('FRAME',f'frame:{asof}',now(),decision)
                                if now()-asof<=60000 and asof>=seed['start']:
                                    if decision['action']:
                                        sign=1 if decision['action']=='BUY' else -1
                                        signal_row=dict(id=asof//INTERVAL,symbol='XRPUSDT',action=decision['action'],
                                            entry=decision['reference']*(1+sign*.003),stop_loss=decision['stop'],
                                            take_profit=decision['target'],created_at=asof,strategy=decision.get('selected','selector'),
                                            input_hash=decision['input_hash'])
                                        book.offer(signal_row,lot,now())
                                    book.protect(quote,now(),asof)
                        health['bar_count']=count
                    except Exception as e:
                        health.update(last_error=type(e).__name__,stage='DATA_GAP',data_ok=False);book.error(now(),'bars',e);last_bar_fetch=now()
                if book.state['funding_pending'] and now()>=fund_retry_at:
                    try:
                        key,event=next(iter(book.state['funding_pending'].items()))
                        rate,mark=market.funding(event['symbol'],event['at']);book.apply_funding(key,rate,mark,now())
                    except Exception as e: book.error(now(),'funding',e)
                    fund_retry_at=now()+60000
                if int(time.time()*1000)-clock['local_at']>600000:
                    clock=market.calibrate();health['clock']=clock
                if successful_quote and health['data_ok']:
                    health['stage']='RUNNING'
                if health['consecutive_errors']>=10: raise RuntimeError('market circuit breaker: ten consecutive quote failures')
                if now()-last_equity>=60000:
                    with book.atomic():book.emit('EQUITY',f'equity:{now()//60000}',now(),dict(at=now(),
                        primary=book.state['arms']['profit_protect']['equity_liquidation'],control=book.state['arms']['source_exit']['equity_liquidation']))
                    last_equity=now()
                value=report(book,root,health,quote)
                if now()-last_notice>=60000:
                    print(json.dumps(dict(stage=value['stage'],poll=poll,counts=value['counts'],net=value['accounting'])),flush=True);last_notice=now()
                time.sleep(5)
        finally:
            health['stage']='STOPPED';report(book,root,health,quote);book.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--proxy')
    p.add_argument('--max-polls',type=int);a=p.parse_args();run(a.root,a.proxy,a.max_polls)
