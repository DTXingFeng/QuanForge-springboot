"""20-USDT feasibility, leverage stress, and two fixed 90-day carry experiments.

Public GET capture only. No credentials, orders, leverage-setting or deployment.
The user budget supplement is separate from the retained failed BTC/ETH capture.
"""
import argparse
import gzip
import json
from pathlib import Path
from datetime import datetime,timezone
import conditional_carry as engine
import crypto_edge_research as util
import research_conditional_carry as study

study.PUBLIC=study.PUBLIC|{'/v5/market/funding/history','/v5/market/mark-price-kline','/v5/market/risk-limit'}
ROOT=Path(__file__).resolve().parents[1]


def sources():
    return {name:util.sha(Path(__file__).parent/name) for name in
        ('micro_budget_research.py','conditional_carry.py','research_conditional_carry.py','crypto_edge_research.py')}


def register(directory):
    directory.mkdir(parents=True,exist_ok=False)
    old=json.loads((ROOT/'docs/crypto-research-20261114/protocol.json').read_text(encoding='utf-8'))
    p=dict(registered_utc=datetime.now(timezone.utc).isoformat(),source_hashes=sources(),
        start=old['end_exclusive']-90*util.DAY,end_exclusive=old['end_exclusive'],
        label='20_USDT_USER_BUDGET_SUPPLEMENT_NOT_A_PARAMETER_SEARCH',
        capital='20',historical_symbols=['SOLUSDT','XRPUSDT'],
        feasibility_symbols=['BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT'],
        policies=['cash','static','conditional'],cost_cases=['base','double'],cases=12,
        fees=dict(spot='.001',perp='.00055',slip='.0005'),
        inherited_policy='conditional_carry.py same frozen 21-rate cost hurdle, exits and delays; no retuning',
        historical_leverage='cash-backed equal coin-unit pair; reserve full initial short notional',
        leverage_screen=[1,2,5,10,20,50,100,200],max_public_attempts=96,max_attempts_per_request=2,
        risk_screen=dict(max_modeled_loss='.2',stop='max(2 * mean last 14 hourly true ranges / price, 0.003)',
            liquidation_check='approximate initial margin less maintenance and close fee must cover 1.5x stop; not exact liquidation formula'),
        expiry_screen='current BTC/ETH USDT dated futures, all retained; conservative settlement fee reserve max(public quote fee,0.0005)',
        hypothesis='funding regimes can persist enough to repay costs; historical result may falsify this',
        research_limit='90-day sample, no annualisation claim or future profitability certification')
    util.dump(directory/'protocol.json',p);return p


def mark_bars(client,symbol,start,end):
    found={};cursor=end-1
    while cursor>=start:
        rows=client.get('/v5/market/mark-price-kline',category='linear',symbol=symbol,interval='60',start=start,end=cursor,limit=1000)['list']
        if not rows: raise ValueError('missing mark history')
        for row in rows:
            ts=int(row[0]);bar=[ts]+row[1:5]+['0']
            if start<=ts<end:
                if ts in found and found[ts]!=bar: raise ValueError('conflicting mark duplicate')
                found[ts]=bar
        following=min(int(row[0]) for row in rows)-1
        if following>=cursor: raise ValueError('mark pagination stalled')
        cursor=following
    if set(found)!=set(range(start,end,util.HOUR)): raise ValueError('incomplete marks')
    return [found[t] for t in sorted(found)]


def funding(client,symbol,start,end):
    rates={};cursor=end-1
    while cursor>=start:
        rows=client.get('/v5/market/funding/history',category='linear',symbol=symbol,startTime=start,endTime=cursor,limit=200)['list']
        if not rows: break
        for row in rows:
            t=int(row['fundingRateTimestamp'])
            if start<=t<end:
                if t in rates and rates[t]!=row['fundingRate']: raise ValueError('conflicting funding')
                rates[t]=row['fundingRate']
        following=min(int(row['fundingRateTimestamp']) for row in rows)-1
        if following>=cursor: raise ValueError('funding pagination stalled')
        cursor=following
    if set(rates)!=set(range(start,end,8*util.HOUR)): raise ValueError('funding schedule outside supported constant 8h model')
    return rates


def capture(directory,p):
    client=study.Capture(directory);history={};instruments={}
    # Obtain feasibility first, before the new historical result is examined.
    for symbol in p['feasibility_symbols']:
        instruments[symbol]={category:client.get('/v5/market/instruments-info',category=category,symbol=symbol)['list'][0]
                             for category in ('spot','linear')}
    tickers=client.get('/v5/market/tickers',category='linear')['list']
    server_time=int(json.loads((directory/client.receipts[-1]['file']).read_text(encoding='utf-8'))['time'])
    spot_tickers={symbol:client.get('/v5/market/tickers',category='spot',symbol=symbol)['list'][0]
        for symbol in p['feasibility_symbols']}
    recent={symbol:client.get('/v5/market/kline',category='linear',symbol=symbol,interval='60',limit=48)['list']
        for symbol in p['feasibility_symbols']}
    risks={symbol:client.get('/v5/market/risk-limit',category='linear',symbol=symbol)['list']
        for symbol in p['feasibility_symbols']}
    expiries=[]
    for base in ('BTC','ETH'):
        page=client.get('/v5/market/instruments-info',category='linear',baseCoin=base,limit=1000)
        if page.get('nextPageCursor'): raise ValueError('expiry inventory incomplete')
        expiries.extend(page['list'])
    util.dump(directory/'current-snapshot.json',dict(server_time=server_time,instruments=instruments,
        linear_tickers=tickers,spot_tickers=spot_tickers,recent_bars=recent,risk_limits=risks,expiry_instruments=expiries))
    for symbol in p['historical_symbols']:
        history[symbol]=dict(spot_instrument=instruments[symbol]['spot'],linear_instrument=instruments[symbol]['linear'],
            spot=client.bars(symbol,'spot',p['start'],p['end_exclusive']),
            linear=client.bars(symbol,'linear',p['start'],p['end_exclusive']),
            marks=mark_bars(client,symbol,p['start'],p['end_exclusive']),
            funding=funding(client,symbol,p['start'],p['end_exclusive']))
    util.dump(directory/'historical-data.json',history)
    util.dump(directory/'capture-manifest.json',dict(attempts=len(client.receipts),
        failures=sum(r['status']!='OK' for r in client.receipts),
        historical_data_sha256=util.sha(directory/'historical-data.json'),current_snapshot_sha256=util.sha(directory/'current-snapshot.json')))


def feasibility(snapshot,p):
    rows=[];tickers={t['symbol']:t for t in snapshot['linear_tickers']}
    for symbol in p['feasibility_symbols']:
        instrument=snapshot['instruments'][symbol]['linear'];lot=instrument['lotSizeFilter'];ticker=tickers[symbol]
        price=util.n(ticker['lastPrice']);step=util.n(lot['qtyStep'])
        bars=sorted([b for b in snapshot['recent_bars'][symbol] if int(b[0])+util.HOUR<=snapshot['server_time']],key=lambda b:int(b[0]))
        trs=[max(util.n(b[2])-util.n(b[3]),abs(util.n(b[2])-util.n(a[4])),abs(util.n(b[3])-util.n(a[4]))) for a,b in zip(bars,bars[1:])]
        if len(trs)<14: raise ValueError('insufficient closed ATR history')
        stop=max(sum(trs[-14:])/14/price*2,util.n('.003'))
        tier=min(snapshot['risk_limits'][symbol],key=lambda t:util.n(t['riskLimitValue']))
        maxlev=min(util.n(instrument['leverageFilter']['maxLeverage']),util.n(tier['maxLeverage']))
        mmr=util.n(tier['maintenanceMargin']);cost=2*(util.n(p['fees']['perp'])+util.n(p['fees']['slip']))
        qty=util.floor_qty(util.n('.2')/(price*(stop+cost)),step);notional=qty*price
        minimum_qty=max(util.n(lot['minOrderQty']),
            (util.n(lot['minNotionalValue'])/price/step).to_integral_value(rounding='ROUND_CEILING')*step)
        for leverage in p['leverage_screen']:
            initial=notional/leverage;roundtrip=notional*cost
            buffer=1/util.n(leverage)-mmr-util.n(p['fees']['perp'])
            valid=qty>=minimum_qty and initial+roundtrip<=util.n(p['capital']) and leverage<=maxlev and buffer>=stop*util.n('1.5')
            rows.append(dict(symbol=symbol,leverage=leverage,max_leverage=util.s(maxlev),price=util.s(price),
                minimum_contract_notional=util.s(minimum_qty*price),risk_sized_qty=util.s(qty),risk_sized_notional=util.s(notional),
                stop_fraction=util.s(stop),modeled_loss_at_stop_including_cost=util.s(notional*(stop+cost)),
                approximate_margin_buffer_fraction=util.s(buffer),initial_margin=util.s(initial),
                roundtrip_fee_and_slip=util.s(roundtrip),passes_approximate_screen=valid,
                failures=[name for failed,name in [(qty<minimum_qty,'BELOW_MINIMUM'),(initial+roundtrip>util.n(p['capital']),'CAPITAL'),
                    (leverage>maxlev,'UNSUPPORTED_LEVERAGE'),(buffer<stop*util.n('1.5'),'STOP_TOO_CLOSE_TO_MARGIN_LIMIT')] if failed]))
    return rows


def expiry_screen(snapshot,p):
    tickers={t['symbol']:t for t in snapshot['linear_tickers']};rows=[]
    for info in snapshot['expiry_instruments']:
        if info.get('contractType')!='LinearFutures' or info.get('settleCoin')!='USDT' or info.get('baseCoin') not in ('BTC','ETH'):
            continue
        ticker=tickers.get(info['symbol'],{});bid=util.n(ticker.get('bid1Price') or 0)
        ask=util.n(snapshot['spot_tickers'][info['baseCoin']+'USDT']['ask1Price'])
        if bid<=0 or int(info['deliveryTime'])<=snapshot['server_time']: continue
        delivery=max(util.n(ticker.get('deliveryFeeRate') or 0),util.n('.0005'))
        # Current-spot price level is only a fee estimate, not a known future exit price.
        basis=bid/ask-1;cost=util.n('.001')+bid/ask*util.n('.00055')+util.n('.001')+delivery+util.n('.0015')
        rows.append(dict(symbol=info['symbol'],spot_ask=util.s(ask),future_bid=util.s(bid),
            raw_basis_pct=util.s(basis*100),modeled_cost_pct=util.s(cost*100),
            indicative_net_per_spot_notional_pct=util.s((basis-cost)*100),
            conservative_net_after_30bp_settlement_mismatch_and_double_exit_price_fees_pct=
                util.s((basis-cost-util.n('.003')-util.n('.001')-delivery)*100),
            quoted_delivery_fee=ticker.get('deliveryFeeRate'),reserved_delivery_fee=util.s(delivery),
            days_to_expiry=util.s(util.n(int(info['deliveryTime'])-snapshot['server_time'])/util.DAY),
            future_minimum_notional=util.s(util.n(info['lotSizeFilter']['minOrderQty'])*bid),
            note='asynchronous quote screen; no fill guarantee, exact settlement match or margin feasibility certified'))
    return rows


def evaluate(directory,p):
    if sources()!=p['source_hashes']: raise ValueError('registered source changed')
    manifest=json.loads((directory/'capture-manifest.json').read_text(encoding='utf-8'))
    for file,key in [('historical-data.json','historical_data_sha256'),('current-snapshot.json','current_snapshot_sha256')]:
        if util.sha(directory/file)!=manifest[key]: raise ValueError('input changed')
    data=json.loads((directory/'historical-data.json').read_text(encoding='utf-8'));runs=[]
    snapshot=json.loads((directory/'current-snapshot.json').read_text(encoding='utf-8'))
    for symbol,b in data.items():
        sl=b['spot_instrument']['lotSizeFilter'];pl=b['linear_instrument']['lotSizeFilter']
        for cost in p['cost_cases']:
            mult=1 if cost=='base' else 2;sf=util.n(p['fees']['spot'])*mult;pf=util.n(p['fees']['perp'])*mult
            slip=util.n(p['fees']['slip'])*mult
            for policy in p['policies']:
                r=engine.replay(b['spot'],b['linear'],b['marks'],b['funding'],p['start'],p['end_exclusive'],policy,
                    p['capital'],sf,pf,slip,max(util.n(sl['basePrecision']),util.n(pl['qtyStep'])),
                    max(util.n(sl['minOrderQty']),util.n(pl['minOrderQty'])),max(util.n(sl['minOrderAmt']),util.n(pl['minNotionalValue'])))
                r.update(symbol=symbol,cost_case=cost,policy=policy,capital=p['capital'],end_exclusive=p['end_exclusive'])
                r['independent_accounting']=study.check_accounting(r,b,sf,pf);runs.append(r)
    util.dump(directory/'results.json',dict(runs=runs,leverage_feasibility=feasibility(snapshot,p),expiry_screen=expiry_screen(snapshot,p)))
    print(json.dumps(dict(cases=len(runs),reconciled=sum(r['independent_accounting']['status']=='RECONCILED' for r in runs))))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['capture','resume','replay'])
    parser.add_argument('--directory',type=Path,required=True);args=parser.parse_args();directory=args.directory
    p=register(directory) if args.action=='capture' else json.loads((directory/'protocol.json').read_text(encoding='utf-8'))
    if sources()!=p['source_hashes']: raise ValueError('registered source changed')
    if args.action in ('capture','resume'): capture(directory,p)
    else: evaluate(directory,p)


if __name__=='__main__': main()
