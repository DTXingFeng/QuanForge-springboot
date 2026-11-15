"""Closed-trade path diagnosis only, not causal attribution or a strategy optimiser."""
import argparse
import collections
import csv
import hashlib
import json
import statistics
from pathlib import Path
from verified_paper import number, text
from strategy_lab import INTERVAL


def excursions(bars,trade,distance):
    # Entry is at bar open. The stop bar can contain prices AFTER exit, so exclude it.
    stop_exit=trade['reason']=='SL_INTRABAR_TIME_UNKNOWN'
    held=[b for b in bars if b[0]>=trade['entered'] and
          (b[0]+INTERVAL<trade['exited'] if stop_exit else b[0]+INTERVAL<=trade['exited'])]
    if not held:return dict(covered_full_bars=0,mfe_r=None,mae_r=None)
    entry=float(trade['entry']);buy=trade['side']=='BUY'
    favorable=max(b[2] for b in held)-entry if buy else entry-min(b[3] for b in held)
    adverse=entry-min(b[3] for b in held) if buy else max(b[2] for b in held)-entry
    return dict(covered_full_bars=len(held),mfe_r=max(0.,favorable/distance),mae_r=max(0.,adverse/distance))


def audit(private,results,output):
    output.mkdir(parents=True,exist_ok=True)
    report=json.loads(results.read_text(encoding='utf-8'))
    data_path=private/'dataset.json'
    if hashlib.sha256(data_path.read_bytes()).hexdigest()!=report['dataset_sha256']:raise ValueError('changed input data')
    bars=json.loads(data_path.read_text(encoding='utf-8'))['bars'];indices={b[0]:i for i,b in enumerate(bars)}
    summaries=[];rows=[]
    for arm in ['ema_cross','breakout','mean_reversion']:
        source=private/f'fixed-{arm}-last_30_days-MODELED_COSTS.json'
        result=json.loads(source.read_text(encoding='utf-8'));trades=result['trades'];local=[]
        for j,t in enumerate(trades):
            i=indices[t['entered']];history=bars[max(0,i-30):i]
            tr=[max(b[2]-b[3],abs(b[2]-a[4]),abs(b[3]-a[4])) for a,b in zip(history,history[1:])]
            distance=sum(tr[-14:])/14*1.2
            prior=trades[j-1] if j else None
            row=dict(arm=arm,trade_index=j,**t,**excursions(bars,t,distance),initial_stop_pct=distance/float(t['entry'])*100,
                same_side_reentry_within_15m=bool(prior and prior['side']==t['side'] and 0<=t['entered']-prior['exited']<=INTERVAL),
                held_minutes=(t['exited']-t['entered'])/60000)
            local.append(row);rows.append(row)
        losses=[t for t in local if number(t['net'])<0]
        observed_losses=[t for t in losses if t['mfe_r'] is not None]
        summaries.append(dict(arm=arm,closed=len(trades),wins=sum(number(t['net'])>0 for t in trades),losses=len(losses),
            exit_reasons=dict(collections.Counter(t['reason'] for t in trades)),
            price_pnl_after_slippage=result['realized_gross_after_slippage'],fees=result['fees'],funding_cost=result['funding_cost_signed'],
            net_closed=text(sum((number(t['net']) for t in trades),number(0))),
            losses_with_fully_observed_pre_exit_bars=len(observed_losses),
            losses_with_observed_mfe_at_least_half_r=sum(t['mfe_r']>=.5 for t in observed_losses),
            losses_with_observed_mfe_at_least_one_r=sum(t['mfe_r']>=1 for t in observed_losses),
            stopped_in_entry_bar=sum(t['reason']=='SL_INTRABAR_TIME_UNKNOWN' and t['held_minutes']==15 for t in local),
            fast_same_direction_reentries=sum(t['same_side_reentry_within_15m'] for t in local),
            median_initial_stop_pct=statistics.median(t['initial_stop_pct'] for t in local),
            median_holding_minutes=statistics.median(t['held_minutes'] for t in local),
            side_net={side:text(sum((number(t['net']) for t in trades if t['side']==side),number(0))) for side in ['BUY','SELL']},
            trade_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    summary=dict(scope='EXPLORATORY_DIAGNOSIS_OF_SIMULATED_CLOSED_TRADES',dataset_sha256=report['dataset_sha256'],
                 summaries=summaries,notes=['MFE excludes the unknown-order stop bar; missing coverage stays unknown',
                    'Prior floating profit does not prove an earlier exit would improve net performance',
                    'Frequent reentry does not by itself prove chasing or a bug','No causal loss percentages or profitable strategy certification'])
    (output/'trade-diagnosis.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    with (output/'trade-diagnosis.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--private',type=Path,required=True)
    parser.add_argument('--results',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(audit(args.private,args.results,args.output),indent=2))
