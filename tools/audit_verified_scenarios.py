"""Ten deterministic engineering scenarios, frozen config, no network or parameter search."""
import argparse
import json
import tempfile
from pathlib import Path
from verified_paper import Ledger, Paper, number, text


def scenario(name, config):
    interval=config['interval_ms']; n=config['warmup']; start=n*interval
    raw=[(i*interval,100.,101.,99.,100.,1.) for i in range(n)]
    short=name=='fast_down'
    first=(start,100.,101. if short else 111.,89. if short else 99.,90. if short else 110.,1.)
    errors=[]
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'paper.sqlite'; ledger=Ledger(path)
        paper=Paper(ledger,config,start); paper.process(raw,start)
        raw.append(first); now=start+interval
        paper.process(raw,now); paper.observe_quote('90' if short else '110',now+1000,now+1000)
        if name=='restart':
            ledger.close();ledger=Ledger(path);paper=Paper(ledger,config,now+1000)
        if name=='api_timeout':
            # A transport error supplies no bar, so the existing cursor and exposure remain.
            try:raise TimeoutError('controlled transport failure')
            except TimeoutError:errors.append('TimeoutError')
        if name in ('network_outage','api_timeout'):
            # Protection on a fresh quote is independent of successful kline ingestion.
            paper.observe_quote('90',now+180000,now+180000)
        elif name=='extreme_volatility':
            paper.observe_quote('70',now+2000,now+2000)
        for i in range(1,5):
            close=110.+i*3 if name=='fast_up' else 90.-i*3 if short else 110.
            bar=(start+i*interval,close,max(close,110.)+1,min(close,110.)-1,close,1.) if not short else (
                 start+i*interval,close,close+1,close-1,close,1.)
            raw.append(bar)
            incoming=list(reversed(raw)) if name=='out_of_order' else list(raw)
            if name=='duplicate_response':incoming.append(incoming[-1])
            if name=='missing_data':incoming=[b for b in incoming if b[0]!=start+interval]
            if name=='network_outage' and i<3:continue
            try:
                paper.process(incoming,start+(i+1)*interval)
                if name=='duplicate_response':paper.process(incoming,start+(i+1)*interval)
            except ValueError as error:errors.append(str(error))
        result=paper.report()
        fills=[p for _,kind,_,p in ledger.events() if kind=='FILL']
        result.update(scenario=name,synthetic=True,errors=errors,
            slippage_assumed=text(sum((abs(number(p['price'])-number(p['reference']))*number(p['qty']) for p in fills),number(0))),
            exit_observation_delay_from_assumed_effective_ms=[p['observed_at']-p['effective_at'] for p in fills if p['role']=='EXIT'],
            intrabar_trigger_delay='UNKNOWN',
            unmanaged_position_detected=bool(paper.state['position'] and not all(
                paper.state['position'].get(k) for k in ['trade','qty','entry','stop','stop_effective'])))
        if result['entries']!=1 or result['unmanaged_position_detected']:
            raise AssertionError('duplicate entry or missing local position ownership')
        if name=='missing_data' and not errors:raise AssertionError('gap was accepted')
        ledger.close()
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();config=json.loads(args.config.read_text(encoding='utf-8'))
    names=['normal','fast_up','fast_down','extreme_volatility','network_outage','restart','api_timeout',
           'duplicate_response','missing_data','out_of_order']
    results=[scenario(name,config) for name in names]
    args.output.write_text(json.dumps(dict(scope='SYNTHETIC_ENGINEERING_ONLY',config=config,results=results),indent=2)+'\n',encoding='utf-8')
    print(json.dumps([dict(scenario=r['scenario'],entries=r['entries'],closed=r['closed'],errors=len(r['errors'])) for r in results],indent=2))
