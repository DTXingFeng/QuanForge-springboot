"""Prospective paired AI veto trial; no model calls, account clients or retrospective predictions.

Local receipts are a causal collection safeguard, not tamper-proof attestation.
All frames, missing results and failures are retained; unknown cost blocks claims.
"""
import argparse
import hashlib
import json
import random
import time
from decimal import Decimal
from pathlib import Path
from verified_paper import Ledger, canonical, number, text

WEEK=7*86400000


class Trial:
    def __init__(self,path,protocol,now):
        self.ledger=Ledger(path)
        self.protocol=protocol
        pinned=protocol.get('evaluator_sha256')
        if pinned and pinned!=hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            self.ledger.close()
            raise ValueError('evaluator implementation changed')
        self.hash=hashlib.sha256(canonical(protocol).encode()).hexdigest()
        registration=[(ts,p) for _,k,ts,p in self.ledger.events() if k=='TRIAL_REGISTERED']
        if registration:
            self.start,self.registration=registration[0]
            if self.registration['hash']!=self.hash:
                self.ledger.close()
                raise ValueError('trial protocol changed')
        else:
            self.start=now
            self.registration=dict(hash=self.hash,protocol=protocol)
            with self.ledger.db:self.ledger.append('trial','TRIAL_REGISTERED',now,self.registration)

    def close(self):self.ledger.close()

    def find(self,kind,frame):
        return next(((ts,p) for _,k,ts,p in self.ledger.events() if k==kind and p.get('frame')==frame),None)

    def frame(self,asof,snapshot,baseline,now):
        p=self.protocol
        if (asof<self.start or asof>now or now-asof>p['decision_ttl_ms']
            or asof%p['interval_ms'] or asof>=self.start+p['window_days']*86400000
            or snapshot.get('closed_only') is not True or snapshot.get('data_through_ms',asof+1)>asof
            or baseline not in ('BUY','SELL','HOLD')):
            raise ValueError('not a current closed forward frame')
        identity=hashlib.sha256(canonical(dict(symbol=p['symbol'],asof=asof,snapshot=snapshot)).encode()).hexdigest()
        existing=[payload for _,kind,_,payload in self.ledger.events() if kind=='FRAME' and payload['asof']==asof]
        payload=dict(frame=identity,asof=asof,deadline=asof+p['decision_ttl_ms'],snapshot=snapshot,baseline=baseline)
        if existing:
            if existing[0]!=payload:raise ValueError('frame revision or duplicate asof')
            return identity
        with self.ledger.db:self.ledger.append('frame:'+identity,'FRAME',now,payload)
        return identity

    def prediction(self,frame,decision,model,prompt_hash,api_cost,now):
        found=self.find('FRAME',frame)
        if found is None:raise ValueError('unknown frame')
        _,snapshot=found
        if self.find('AI',frame):raise ValueError('first AI receipt is immutable; no answer selection')
        valid=(found[0]<=now<=snapshot['deadline'] and self.find('OUTCOME',frame) is None
               and decision in ('TAKE','SKIP') and model==self.protocol['model']
               and prompt_hash==self.protocol['prompt_hash'])
        cost=None if api_cost is None else number(api_cost)
        if cost is not None and cost<0:raise ValueError('negative API cost')
        payload=dict(frame=frame,decision=decision,model=model,prompt_hash=prompt_hash,
                     api_cost=text(cost) if cost is not None else None,valid=valid,
                     fallback='TAKE',receipt_ms=now)
        with self.ledger.db:self.ledger.append('ai:'+frame,'AI',now,payload)
        return valid

    def outcome(self,frame,costs,settled,now):
        found=self.find('FRAME',frame)
        if found is None or not found[0]<=settled<=now:raise ValueError('outcome before frame or future settlement')
        if self.find('OUTCOME',frame):raise ValueError('outcome already sealed')
        normalized={key:(text(costs[key]) if costs.get(key) is not None else None)
                    for key in ['gross','fees','funding','slippage']}
        if any(number(normalized[k])<0 for k in ['fees','slippage'] if normalized[k] is not None):
            raise ValueError('negative fees/slippage; rebates require explicit model')
        with self.ledger.db:self.ledger.append('outcome:'+frame,'OUTCOME',now,dict(frame=frame,costs=normalized,settled=settled))

    def evaluate(self,now):
        events=self.ledger.events();p=self.protocol
        frames=[x for _,kind,_,x in events if kind=='FRAME']
        blocked=[];missing=unknown=invalid=0;baseline_total=Decimal(0);ai_total=Decimal(0)
        if p.get('model_identity_verified') is not True:blocked.append('MODEL_VERSION_NOT_ATTESTED')
        if not p.get('evaluator_sha256'):blocked.append('EVALUATOR_NOT_PINNED')
        groups={};opportunities=0
        for frame in frames:
            ai=self.find('AI',frame['frame']);out=self.find('OUTCOME',frame['frame'])
            if not ai:missing+=1
            if ai and not ai[1]['valid']:invalid+=1
            if not out:
                blocked.append('OUTCOMES_PENDING');continue
            costs=out[1]['costs']
            if any(v is None for v in costs.values()) or ai is None or ai[1]['api_cost'] is None:
                unknown+=1;continue
            base=number(costs['gross'])-number(costs['fees'])-number(costs['funding'])-number(costs['slippage'])
            if frame['baseline']=='HOLD' and base!=0:
                blocked.append('NONZERO_HOLD_OUTCOME');continue
            opportunities+=frame['baseline']!='HOLD'
            decision=ai[1]['decision'] if ai[1]['valid'] else 'TAKE'
            assisted=(base if decision=='TAKE' else Decimal(0))-number(ai[1]['api_cost'])
            baseline_total+=base;ai_total+=assisted
            block=(frame['asof']-self.start)//WEEK
            groups[block]=groups.get(block,Decimal(0))+assisted-base
        interval=p['interval_ms'];first=(self.start+interval-1)//interval*interval
        # Only elapsed decision deadlines are due; do not invent future scheduled frames.
        last=min(now-p['decision_ttl_ms'],self.start+p['window_days']*86400000-1)
        expected=max(0,(last-first)//interval+1)
        due={f['asof'] for f in frames if f['asof']<=last}
        if len(due)!=expected:blocked.append('FORWARD_FRAME_COVERAGE_INCOMPLETE')
        if not frames:blocked.append('NO_FORWARD_FRAMES')
        if missing:blocked.append('AI_PREDICTIONS_MISSING')
        if invalid:blocked.append('INVALID_OR_LATE_AI')
        if unknown:blocked.append('COSTS_UNKNOWN')
        ai_rows=[payload for _,kind,_,payload in events if kind=='AI']
        paid=[number(row['api_cost']) for row in ai_rows if row['api_cost'] is not None and number(row['api_cost'])>0]
        if ('max_paid_calls' in p and len(paid)>p['max_paid_calls']) or (
                'api_cost_budget_usdt' in p and sum(paid,Decimal(0))>number(p['api_cost_budget_usdt'])):
            blocked.append('AI_COST_BUDGET_EXCEEDED')
        if opportunities<p['min_opportunities']:blocked.append('INSUFFICIENT_OPPORTUNITIES')
        completed=[float(value) for block,value in sorted(groups.items()) if self.start+(block+1)*WEEK<=now]
        if len(completed)<p['min_week_blocks']:blocked.append('INSUFFICIENT_WEEK_BLOCKS')
        ci=None
        if len(completed)>=p['min_week_blocks']:
            rng=random.Random(p['seed'])
            draws=sorted(sum(rng.choice(completed) for _ in completed)/len(completed) for _ in range(p['bootstrap_samples']))
            ci=[draws[int(.025*(len(draws)-1))],draws[int(.975*(len(draws)-1))]]
        if ci is None or ci[0]<=0:blocked.append('NO_POSITIVE_PAIRED_INTERVAL')
        if ai_total<=0:blocked.append('AI_NET_NOT_POSITIVE')
        return dict(scope='REGISTERED_FORWARD_AI_VETO_ONLY',protocol_hash=self.hash,registered_ms=self.start,
            frames=len(frames),due_frames_expected=expected,closed_opportunities=opportunities,
            missing_ai=missing,invalid_or_late_ai=invalid,unknown_cost_rows=unknown,
            baseline_net_known_subset=text(baseline_total),ai_net_known_subset=text(ai_total),
            paired_delta=text(ai_total-baseline_total),weekly_mean_delta_ci95=ci,
            completed_week_blocks=len(completed),blocked=sorted(set(blocked)),ai_increment_proven=not blocked,
            policy='TAKE/SKIP only; invalid/late falls back to baseline and still pays observed API cost',
            warning='Known subsets are diagnostic, never full performance when costs/coverage are incomplete. '
                    'Weekly resampling does not guarantee independent markets or future profits.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--protocol',type=Path,required=True)
    parser.add_argument('--db',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();protocol=json.loads(args.protocol.read_text(encoding='utf-8'))
    trial=Trial(args.db,protocol,int(time.time()*1000))
    try:
        result=trial.evaluate(int(time.time()*1000));args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2))
    finally:trial.close()
