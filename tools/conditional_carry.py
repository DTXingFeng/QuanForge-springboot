"""Causal conditional-carry research. No network, credentials, or order interface."""
from bisect import bisect_right
from crypto_edge_research import D,n,s,HOUR,DAY,floor_qty


class FundingHistory:
    def __init__(self,rates):
        self.rates=sorted((int(t),n(v)) for t,v in rates.items())
        self.times=[t for t,_ in self.rates]
    def published(self,asof):
        # Historical rates are assumed usable one hour after settlement.
        return self.rates[max(0,bisect_right(self.times,asof-HOUR)-21):bisect_right(self.times,asof-HOUR)]


def entry_decision(rates,asof,spot_fee,perp_fee,slip):
    history=rates if isinstance(rates,FundingHistory) else FundingHistory(rates)
    window=history.published(asof)
    if len(window)!=21 or asof-window[-1][0]>16*HOUR:
        return dict(enter=False,reason='INSUFFICIENT_OR_STALE_HISTORY')
    if any(b[0]-a[0]!=8*HOUR for a,b in zip(window,window[1:])):
        return dict(enter=False,reason='FUNDING_GAP')
    mean7=sum(v for _,v in window)/21
    mean1=sum(v for _,v in window[-3:])/3
    forecast=min(mean7,mean1)*90  # hypothesis: conservative recent rate persists 30 days
    cost=2*(n(spot_fee)+n(perp_fee))+4*n(slip)
    positive=sum(v>0 for _,v in window)
    enter=positive>=17 and forecast>=cost*n('1.5') and forecast>0
    return dict(enter=enter,reason='COST_HURDLE_PASSED' if enter else 'NO_COST_ADJUSTED_OPPORTUNITY',
        last_rate_at=window[-1][0],forecast_30d_per_notional=s(forecast),
        roundtrip_cost_fraction=s(cost),positive_settlements=positive)


def replay(spot,perp,marks,rates,start,end,policy,capital='200',spot_fee='.001',perp_fee='.00055',
           slip='.0005',qty_step='.001',min_qty='0',min_notional='0'):
    """Hourly pairs; cash-funded hedge; one-hour decision-to-execution delay.

    Funding is credited before boundary exits and never to boundary entries.
    Entry/exit fills are modeled simultaneously, not evidence of two-leg execution.
    Reserve exhaustion invalidates executable return rather than inventing a fill.
    """
    if policy not in ('cash','static','conditional'): raise ValueError('unknown policy')
    pp={b[0]:b for b in perp};mm={b[0]:b for b in marks};hist=FundingHistory(rates)
    fund_rates={int(t):n(v) for t,v in rates.items()}
    observed=[b for b in spot if start<=b[0]<end]
    expected=set(range(start,end,HOUR))
    if len(observed)!=len(expected) or len(pp)!=len(perp) or len(mm)!=len(marks):
        raise ValueError('duplicate hourly data')
    if [b[0] for b in observed]!=sorted(expected) or not expected.issubset(pp) or not expected.issubset(mm):
        raise ValueError('missing or unaligned hourly data')
    if not {t for t in expected if t%(8*HOUR)==0}.issubset(fund_rates):
        raise ValueError('funding coverage incomplete')
    initial=n(capital);cash=initial;p=None;pending=None;fees=D(0);funding=D(0)
    gross=D(0);slippage=D(0);peak=initial;dd=D(0);halted=False;failure=None;cooldown_until=start
    orders=[];trades=[];curve=[];entries=0;invested=0;blocked=0;opportunities=0;worst_ratio=None
    def nav(sp,pe):
        if p is None: return cash
        sx=n(sp)*(1-n(slip));px=n(pe)*(1+n(slip))
        return cash+p['qty']*sx+p['qty']*(p['perp_entry']-px)-p['qty']*(sx*n(spot_fee)+px*n(perp_fee))
    def enter(at,sp,pe,decision):
        nonlocal cash,p,fees,slippage,entries,blocked
        sb=n(sp)*(1+n(slip));ps=n(pe)*(1-n(slip))
        q=floor_qty(cash/(sb*(1+n(spot_fee))+ps*(1+n(perp_fee))),qty_step)
        if q<=0 or q<n(min_qty) or min(q*sb,q*ps)<n(min_notional):
            blocked+=1;return
        paid=q*(sb*n(spot_fee)+ps*n(perp_fee));cash-=q*sb+paid;fees+=paid
        slippage+=q*n(slip)*(n(sp)+n(pe));entries+=1
        p=dict(qty=q,spot_entry=sb,perp_entry=ps,entered=at,entry_equity=cash+q*sb+paid,
            entry_fees=paid,funding=D(0),entry_decision=decision)
        orders.append(dict(at=at,action='OPEN_PAIR',qty=s(q),spot_reference=s(sp),perp_reference=s(pe),
            spot_fill=s(sb),perp_fill=s(ps),fees=s(paid),decision=decision))
    def close(at,sp,pe,reason,decision_asof):
        nonlocal cash,p,fees,slippage,gross,cooldown_until
        sx=n(sp)*(1-n(slip));px=n(pe)*(1+n(slip));q=p['qty']
        paid=q*(sx*n(spot_fee)+px*n(perp_fee));price_pnl=q*(sx-p['spot_entry']+p['perp_entry']-px)
        cash+=q*sx+q*(p['perp_entry']-px)-paid;fees+=paid;gross+=price_pnl
        slippage+=q*n(slip)*(n(sp)+n(pe))
        trades.append(dict(entry_at=p['entered'],exit_at=at,decision_asof=decision_asof,reason=reason,
            qty=s(q),funding=s(p['funding']),fees=s(p['entry_fees']+paid),
            price_pnl_after_slippage=s(price_pnl),net_pnl=s(price_pnl+p['funding']-p['entry_fees']-paid)))
        orders.append(dict(at=at,action='CLOSE_PAIR',qty=s(q),spot_reference=s(sp),perp_reference=s(pe),
            spot_fill=s(sx),perp_fill=s(px),fees=s(paid),decision_asof=decision_asof,reason=reason))
        p=None;cooldown_until=at+7*DAY
    for b in observed:
        ts=b[0];pb=pp[ts];mb=mm[ts]
        if p and ts in fund_rates and p['entered']<ts:
            income=p['qty']*n(mb[1])*fund_rates[ts]
            cash+=income;funding+=income;p['funding']+=income
        if p and cash+p['qty']*(p['perp_entry']-n(mb[1]))<=0:
            failure=ts
            curve.append(dict(at=ts,equity=s(nav(b[1],pb[1]))))
            break
        if pending and pending['execute_at']==ts:
            if pending['action']=='CLOSE' and p:
                close(ts,b[1],pb[1],pending['reason'],pending['asof'])
            elif pending['action']=='OPEN' and p is None and not halted:
                enter(ts,b[1],pb[1],pending)
            pending=None
        if policy=='static' and ts==start: enter(ts,b[1],pb[1],dict(asof=None,rule='PREDECLARED_START'))
        if p:
            invested+=1
            # Conservative independent short margin pressure; no spot collateral offsets.
            ratio=(cash+p['qty']*(p['perp_entry']-n(mb[2])))/(p['qty']*n(mb[2]))
            worst_ratio=ratio if worst_ratio is None else min(worst_ratio,ratio)
            if ratio<=0:
                failure=ts
                curve.append(dict(at=ts+HOUR,equity=s(nav(b[4],pb[4]))))
                break
        value=nav(b[4],pb[4]);peak=max(peak,value);dd=max(dd,1-value/peak)
        asof=ts+HOUR
        if policy=='conditional':
            if value<=peak*n('.97'): halted=True
            reason=None
            recent=hist.published(asof)
            if p:
                if halted: reason='DRAWDOWN_BUDGET'
                elif value<=p['entry_equity']*n('.98'): reason='HEDGE_LOSS'
                elif (cash+p['qty']*(p['perp_entry']-n(mb[4])))/(p['qty']*n(mb[4]))<n('.25'):
                    reason='MARGIN_BUFFER'
                elif len(recent)>=3 and sum(v for _,v in recent[-3:])<=0: reason='FUNDING_REVERSED'
                if reason and pending is None:
                    pending=dict(action='CLOSE',execute_at=asof+HOUR,asof=asof,reason=reason)
            elif not halted and pending is None and asof>=cooldown_until:
                decision=entry_decision(hist,asof,spot_fee,perp_fee,slip)
                if decision['enter']:
                    opportunities+=1
                    pending=dict(action='OPEN',execute_at=asof+HOUR,asof=asof,**decision)
        if ts+HOUR==end and p:
            close(end,b[4],pb[4],'PREDECLARED_TERMINAL_CLOSE',None);value=cash
            peak=max(peak,value);dd=max(dd,1-value/peak)
        if asof%DAY==0 or asof==end: curve.append(dict(at=asof,equity=s(value)))
    final=nav(observed[-1][4],pp[observed[-1][0]][4]) if failure is None else n(curve[-1]['equity'])
    # Ledger identity applies to fully closed cases; failed margin paths retain open obligations.
    residual=None if p else s(final-(initial+gross+funding-fees))
    return dict(status='RESERVE_EXHAUSTED' if failure is not None else 'HISTORICAL_MODEL',
        initial_equity=s(initial),final_equity=s(final),return_pct=None if failure is not None else s((final/initial-1)*100),
        net_pnl=s(final-initial),hourly_close_max_drawdown_pct=s(dd*100),fees=s(fees),
        funding_income=s(funding),price_pnl_after_slippage=s(gross),slippage_diagnostic=s(slippage),
        ledger_residual=residual,entries=entries,leg_orders=len(orders)*2,closed_trades=trades,
        orders=orders,curve=curve,invested_hours=invested,blocked_minimum=blocked,
        qualifying_decisions=opportunities,halted_by_drawdown=halted,reserve_exhausted_at=failure,
        minimum_hourly_short_equity_over_mark_notional=s(worst_ratio) if worst_ratio is not None else None)
