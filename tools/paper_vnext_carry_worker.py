"""Always-on independent 20U carry PAPER worker, using the app's existing proxy."""
import argparse
import hashlib
import json
import os
import signal
import time
import urllib.parse
from pathlib import Path
from paper_vnext_carry import CarryBook
from paper_vnext_market import Market,atomic_json
from paper_vnext_worker import lock
from paper_vnext_ledger import n,text
from paper_vnext_strategy import VERSION


def proxy_config(path):
    p=json.loads(path.read_text());safe={k:p.get(k) for k in ['enabled','type','host','port']}
    if not p.get('enabled'):return None,safe
    if p.get('type')!='HTTP' or not p.get('host') or not 0<int(p['port'])<65536:raise ValueError('paper worker requires a valid HTTP proxy')
    auth=''
    if p.get('username'):auth=urllib.parse.quote(p['username'],safe='')+':'+urllib.parse.quote(p.get('password') or '',safe='')+'@'
    return 'http://'+auth+p['host']+':'+str(p['port']),safe


def instrument(market):
    lot=market.instrument('XRPUSDT')
    spot=market.get('/v5/market/instruments-info',category='spot',symbol='XRPUSDT')['result']['list'][0]
    sl=spot['lotSizeFilter'];step=max(n(sl['basePrecision']),n(lot['qty_step']))
    if step/min(n(sl['basePrecision']),n(lot['qty_step']))%1:raise ValueError('incompatible pair quantity steps')
    return dict(qty_step=text(step),min_qty=text(max(n(sl['minOrderQty']),n(lot['min_qty']))),
        min_notional=text(max(n(sl['minOrderAmt']),n(lot['min_notional']))),spot_tick=spot['priceFilter']['tickSize'],
        perp_tick=lot['tick_size'],maintenance=lot['maintenance'],funding_interval_ms=lot['funding_interval_ms'])


def spot_quote(market):
    value=market.get('/v5/market/tickers',category='spot',symbol='XRPUSDT');r=value['result']['list'][0]
    if r['symbol']!='XRPUSDT':raise ValueError('wrong spot symbol')
    return dict(symbol=r['symbol'],at=int(value['time']),bid=r['bid1Price'],ask=r['ask1Price'],
        bid_size=r['bid1Size'],ask_size=r['ask1Size'],receipt=market.last_receipt)


def perp_quote(market):
    value=market.get('/v5/market/tickers',category='linear',symbol='XRPUSDT');r=value['result']['list'][0]
    if r['symbol']!='XRPUSDT':raise ValueError('wrong perpetual symbol')
    return dict(symbol=r['symbol'],at=int(value['time']),bid=r['bid1Price'],ask=r['ask1Price'],mark=r['markPrice'],
        bid_size=r['bid1Size'],ask_size=r['ask1Size'],next_funding=int(r['nextFundingTime']),funding_rate=r.get('fundingRate'),receipt=market.last_receipt)


def publish(root,book,health,spot,perp):
    s=book.state;now=int(time.time()*1000);a=book.accounting()
    curve=[json.loads(r[0]) for r in book.db.execute("select payload from events where kind='EQUITY' order by at desc limit 288")][::-1]
    recent=[dict(kind=k,at=at,payload=json.loads(p)) for k,at,p in book.db.execute(
        "select kind,at,payload from events where kind not in ('QUOTE','EQUITY') order by at desc limit 24")]
    primary=dict(cash=s['cash'],equity_liquidation=s['equity'],fees=s['fees'],funding_cost=text(-n(s['funding_income'])),
        position=s['position'],trades=s['trades'][-50:],max_drawdown=s['max_drawdown'],peak=s['peak'],invalid=s['invalid'])
    control=dict(cash='20',equity_liquidation='20',fees='0',funding_cost='0',position=None,trades=[],max_drawdown='0',invalid=False)
    value=dict(version=VERSION,mode='PAPER_ONLY',heartbeat=now,worker_pid=os.getpid(),symbol='XRPUSDT',capital='20',
        stage='HALTED' if s['risk_halt'] else 'PAUSED' if s['manual_pause'] else 'RECOVERING' if s['funding_pending'] else health['stage'],
        rules=book.rules,primary=primary,control=control,accounting=dict(profit_protect=a,source_exit=dict(modeled_net_pnl='0',ledger_cash_residual='0',funding_complete_under_model=True)),
        manual_pause=s['manual_pause'],risk_halt=s['risk_halt'],day_halt=False,last_control=s['last_control'],
        funding_pending=len(s['funding_pending']),pending=None,regime=dict(regime='HEDGED',reason='POSITIVE_HISTORY_NOT_FORWARD_CERTIFICATION'),
        quote=perp,spot_quote=spot,health=health,equity_curve=curve,events=recent,started_at=s['seed']['start'],
        counts=dict(book.db.execute('select kind,count(*) from events group by kind')),real_order_capability=False,
        strategy=dict(name='现货与永续等量对冲',policy='cash_carry',paper_passed=False,status='EXPERIMENTAL',
            validation='历史模型有微利；前瞻盈利未过关',mechanisms=['买入现货','等币数做空永续','结算资金费']),
        performance_basis='Model fills from observed bid/ask; modeled fees/slippage; actual settled funding rate with minute mark-open proxy')
    atomic_json(root/'report.json',value);return value


def run(root,proxy_file,max_polls=None):
    root.mkdir(parents=True,exist_ok=True)
    with lock(root/'worker.lock'):
        proxy,safe=proxy_config(proxy_file);market=Market(root/'market-receipts',proxy,budget=40000);clock=market.calibrate()
        def now():return int(time.time()*1000)+clock['offset']+clock['uncertainty']
        paths=['paper_vnext_carry_worker.py','paper_vnext_carry.py','paper_vnext_market.py','paper_vnext_strategy.py','paper_vnext_ledger.py','paper_vnext_worker.py']
        sources={p:hashlib.sha256(Path(__file__).with_name(p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in paths}
        profile=root/'run.json'
        if profile.exists():
            registered=json.loads(profile.read_text())
            if registered['sources']!=sources:raise ValueError('frozen PAPER version changed')
            seed=registered['seed'];lot=registered['instrument']
        else:
            lot=instrument(market);seed=dict(start=now(),version=VERSION,strategy='cash_carry',capital='20')
            atomic_json(profile,dict(seed=seed,instrument=lot,sources=sources))
        book=CarryBook(root/'paper.sqlite',seed,lot);running=True;spot=perp=None;poll=0;last_equity=last_notice=fund_retry=0
        health=dict(stage='CONNECTING',proxy=safe,errors=0,consecutive_errors=0,last_error=None,clock=clock,last_quote_at=None)
        def stop(*_):
            nonlocal running
            running=False
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop);publish(root,book,health,spot,perp)
        try:
            while running and (max_polls is None or poll<max_polls):
                poll+=1
                try:
                    updated,config=proxy_config(proxy_file)
                    if updated!=proxy:
                        proxy=updated;market=Market(root/'market-receipts',proxy,budget=40000);clock=market.calibrate();health['proxy']=config
                    spot=spot_quote(market);perp=perp_quote(market);book.observe(spot,perp,now())
                    health.update(stage='RUNNING',consecutive_errors=0,last_quote_at=perp['at'])
                except Exception as e:
                    health.update(stage='CONNECTION_ERROR',errors=health['errors']+1,consecutive_errors=health['consecutive_errors']+1,last_error=type(e).__name__)
                    book.error(now(),'market',e)
                command=root/'control.json'
                if command.exists():
                    try:
                        c=json.loads(command.read_text());book.control(c['id'],c['action'],now())
                    except Exception as e:book.error(now(),'control',e)
                if book.state['funding_pending'] and now()>=fund_retry:
                    try:
                        key,e=next(iter(book.state['funding_pending'].items()));rate,mark=market.funding(e['symbol'],e['at']);book.funding(key,rate,mark,now())
                    except Exception as e:book.error(now(),'funding',e)
                    fund_retry=now()+60000
                if now()-last_equity>=60000:
                    with book.atomic():book.emit('EQUITY',f'equity:{now()//60000}',now(),dict(at=now(),primary=book.state['equity'],control='20'))
                    last_equity=now()
                if int(time.time()*1000)-clock['local_at']>600000:clock=market.calibrate();health['clock']=clock
                value=publish(root,book,health,spot,perp)
                if health['consecutive_errors']>=10:raise RuntimeError('market breaker: ten consecutive failures')
                if a:=value['accounting']['profit_protect']:
                    if a['ledger_cash_residual']!='0':raise RuntimeError('paper cash reconciliation failed')
                if now()-last_notice>=60000:
                    print(json.dumps(dict(stage=value['stage'],poll=poll,counts=value['counts'],net=value['accounting']['profit_protect'])),flush=True);last_notice=now()
                time.sleep(5)
        finally:
            health['stage']='STOPPED';publish(root,book,health,spot,perp);book.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--proxy-file',type=Path,required=True);p.add_argument('--max-polls',type=int)
    a=p.parse_args();run(a.root,a.proxy_file,a.max_polls)
