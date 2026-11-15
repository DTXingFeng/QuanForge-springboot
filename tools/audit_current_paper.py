"""Describe the captured runtime and test recorded entry candles, public GET only.

No order APIs; old records never rewritten. Equal-notional cost subtraction is a
diagnostic price-return statistic, not a portfolio return or historical account fee.
"""
import argparse
import collections
import datetime as dt
import json
import urllib.parse
import urllib.request
from pathlib import Path
from decimal import Decimal as D
from crypto_edge_research import dump,sha


def epoch(v):
    if v is None: return None
    if isinstance(v,(int,float)): return int(v)
    return int(dt.datetime.fromisoformat(v).replace(tzinfo=dt.timezone.utc).timestamp()*1000)


def summarize(captured):
    now=captured['observed_utc_ms'];dbs=captured['databases'];out={}
    for name,db in dbs.items():
        rows=db['tracks']
        out[name]=dict(rows=len(rows),last_created_ms=max(epoch(r['created_at']) for r in rows),
            status=dict(collections.Counter(r['status'] for r in rows)),
            latest_equity=db.get('equity_snapshots',[])[-1:] or None)
    paper=[r for r in dbs['quanforge.db']['tracks'] if r.get('exec_mode')=='PAPER']
    cohorts=[]
    for days in (1,7,30):
        rows=[r for r in paper if epoch(r['created_at'])>=now-days*86400000]
        closed=[r for r in rows if r['status'] in ('WIN','LOSS') and r['result_pct'] is not None]
        values=[D(str(r['result_pct'])) for r in closed];total=sum(values,D(0))
        terminal=[r for r in rows if r['status'] in ('WIN','LOSS','EXPIRED') and r['result_pct'] is not None]
        terminal_total=sum((D(str(r['result_pct'])) for r in terminal),D(0))
        cohorts.append(dict(created_within_days=days,created=len(rows),closed_win_loss=len(closed),
            status=dict(collections.Counter(r['status'] for r in rows)),wins=sum(v>0 for v in values),
            gross_price_return_sum_pct=str(total),mean_gross_price_return_pct=str(total/len(values)) if values else None,
            assumed_roundtrip_fee_pct='.11',assumed_roundtrip_slip_pct='.10',
            mean_after_assumed_fee_pct=str(total/len(values)-D('.11')) if values else None,
            mean_after_assumed_fee_and_slip_pct=str(total/len(values)-D('.21')) if values else None,
            missing_qty=sum(r.get('qty') is None for r in closed),
            terminal_with_reported_return_including_expired=len(terminal),
            expired_with_reported_return=sum(r['status']=='EXPIRED' for r in terminal),
            terminal_mean_gross_price_pct=str(terminal_total/len(terminal)) if terminal else None,
            terminal_mean_after_assumed_fee_pct=str(terminal_total/len(terminal)-D('.11')) if terminal else None,
            terminal_mean_after_assumed_fee_and_slip_pct=str(terminal_total/len(terminal)-D('.21')) if terminal else None,
            expired_without_reported_return=sum(r['status']=='EXPIRED' and r['result_pct'] is None for r in rows),
            portfolio_net_usdt=None,reason='No reliable quantity/cost ledger; sum of trade price returns is not account return'))
    return dict(observed_utc_ms=now,services=captured['services'],databases=out,
        safe_config=dbs['quanforge.db']['safe_config'],deployed_jar_sha256=captured['deployed_jar_sha256'],cohorts=cohorts)


def check_entries(captured,directory):
    # Last 12 closed PAPER rows, selected by recency before looking at market data.
    rows=[r for r in captured['databases']['quanforge.db']['tracks'] if r.get('exec_mode')=='PAPER'
          and r.get('entered_at') is not None and r['status'] in ('WIN','LOSS')][-12:]
    result=[]
    for row in rows:
        ts=epoch(row['entered_at']);params=dict(category='linear',symbol=row['symbol'],interval=1,start=ts,end=ts+59999,limit=1)
        url='https://api.bybit.com/v5/market/kline?'+urllib.parse.urlencode(params)
        info=dict(id=row['id'],symbol=row['symbol'],side=row['action'],entry=row['entry'],entered_at=ts)
        try:
            with urllib.request.urlopen(url,timeout=12) as response: raw=response.read()
            with (directory/f'entry-{row["id"]}.json').open('xb') as f: f.write(raw)
            value=json.loads(raw);bars=value.get('result',{}).get('list',[])
            if value.get('retCode')!=0 or len(bars)!=1 or int(bars[0][0])!=ts: raise ValueError('missing entry bar')
            b=bars[0];high=D(b[2]);low=D(b[3]);entry=D(str(row['entry']))
            info.update(high=str(high),low=str(low),
                limit_touch_possible=low<=entry if row['action']=='BUY' else high>=entry,
                original_reversed_touch_predicate=high>=entry if row['action']=='BUY' else low<=entry,
                raw_sha256=sha(directory/f'entry-{row["id"]}.json'))
        except Exception as e: info['error_type']=type(e).__name__
        result.append(info)
    return dict(selection='most recent 12 closed PAPER rows before market retrieval',requests=len(rows),
        observed=len([r for r in result if 'limit_touch_possible' in r]),
        recorded_entry_without_valid_limit_touch=sum(r.get('limit_touch_possible') is False for r in result),
        cases=result,note='OHLC touch is necessary, not proof of queue fill; adverse entry below/above limit invalidates the recorded limit fill')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--capture',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);captured=json.loads(args.capture.read_text(encoding='utf-8'))
    report=summarize(captured);report['capture_sha256']=sha(args.capture)
    dump(args.output/'runtime-summary.json',report)
    entries=check_entries(captured,args.output);dump(args.output/'entry-check.json',entries)
    print(json.dumps(dict(cohorts=report['cohorts'],entry_check={k:v for k,v in entries.items() if k!='cases'}),indent=2))


if __name__=='__main__': main()
