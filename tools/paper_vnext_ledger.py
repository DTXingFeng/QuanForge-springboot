"""Paired 20-USDT mechanical PAPER ledger. No network or credential dependency.

Forward executions use observed bid/ask. Historical research explicitly supplies
synthetic OHLC quote scenarios. Both wallets share entries and quantities.
"""
import argparse
import copy
import hashlib
import json
import sqlite3
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from decimal import Decimal as D,ROUND_DOWN,ROUND_CEILING
from paper_vnext_strategy import canonical


def n(v):
    value=D(str(v))
    if not value.is_finite(): raise ValueError('nonfinite value')
    return value
def text(v):
    value=format(n(v),'f')
    return value.rstrip('0').rstrip('.') if '.' in value else value


def adverse_price(value,tick,buy):
    return (value/n(tick)).to_integral_value(rounding=ROUND_CEILING if buy else ROUND_DOWN)*n(tick)


class PaperBook:
    def __init__(self,path,seed):
        self.db=sqlite3.connect(path,timeout=5);self.db.execute('pragma journal_mode=WAL')
        self.db.executescript('create table if not exists state(id integer primary key check(id=1),payload text);'
            'create table if not exists events(id text primary key,kind text,at integer,payload text);')
        self.rules=dict(capital='20',risk_fraction='.01',max_notional_ratio='1',leverage='5',fee='.00055',slip='.0005',
            source_max_age_ms=60000,pending_ttl_ms=60000,quote_max_age_ms=15000,holding_ttl_ms=3600000,
            max_drawdown='.10',profit_protection='at +1R: fee-adjusted breakeven; at +1.5R: trail 0.75R',
            inputs='fresh closed five-minute mechanical decisions; no backfilled entries')
        multiplier=n(seed.get('cost_multiplier',1))
        self.rules['fee']=text(n(self.rules['fee'])*multiplier);self.rules['slip']=text(n(self.rules['slip'])*multiplier)
        fingerprint=hashlib.sha256((hashlib.sha256(Path(__file__).read_bytes()).hexdigest()+canonical(seed)+canonical(self.rules)).encode()).hexdigest()
        old=self.db.execute('select payload from state where id=1').fetchone()
        if old:
            self.state=json.loads(old[0])
            if self.state['fingerprint']!=fingerprint: raise ValueError('frozen trial changed')
        else:
            self.state=dict(fingerprint=fingerprint,seed=seed,watermark=seed['watermark'],pending=None,last_quotes={},
                cursor=None,manual_pause=False,risk_halt=False,day_halt=False,day=seed['start']//86400000,
                day_start={'source_exit':'20','profit_protect':'20'},funding_pending={},funding_done=[],cooldown_until=0,
                entries_today=0,last_control=None,regime=None,last_frame=None,
                arms={name:dict(cash='20',position=None,fees='0',peak='20',max_drawdown='0',trades=[],invalid=False,
                    equity_liquidation='20',mark_at=seed['start'],funding_cost='0')
                      for name in ('source_exit','profit_protect')},entry_disabled=False,ended=False,last_seen=seed['start'])
            with self.atomic(): self.emit('REGISTRATION','registration',seed['start'],dict(rules=self.rules,seed=seed,fingerprint=fingerprint))
    def close(self): self.db.close()
    @contextmanager
    def atomic(self):
        before=copy.deepcopy(getattr(self,'state',None))
        try:
            with self.db:
                yield
                self.db.execute('insert into state values(1,?) on conflict(id) do update set payload=excluded.payload',(canonical(self.state),))
        except Exception:
            self.state=before;raise
    def emit(self,kind,key,at,payload):
        encoded=canonical(payload);old=self.db.execute('select kind,at,payload from events where id=?',(key,)).fetchone()
        if old:
            if old!=(kind,at,encoded): raise ValueError('conflicting event identity')
            return False
        self.db.execute('insert into events values(?,?,?,?)',(key,kind,at,encoded));return True
    def events(self):
        return [dict(id=i,kind=k,at=t,payload=json.loads(p)) for i,k,t,p in self.db.execute('select * from events order by at,id')]
    def error(self,at,stage,error):
        with self.atomic(): self.emit('POLL_ERROR',f'error:{stage}:{at}',at,dict(stage=stage,type=type(error).__name__))
    def reject_source(self,signal,observed,reason):
        with self.atomic():
            identity=int(signal['id'])
            if identity<=self.state['watermark']: return
            self.state['watermark']=identity
            self.emit('SOURCE_SIGNAL',f'source:{identity}',observed,dict(signal=signal))
            self.emit('SOURCE_REJECT',f'reject:{identity}',observed,dict(reason=reason))
    def offer(self,signal,lot,observed):
        with self.atomic():
            identity=int(signal['id'])
            if identity<=self.state['watermark']: return
            self.state['watermark']=identity
            self.emit('SOURCE_SIGNAL',f'source:{identity}',observed,dict(signal=signal,lot=lot))
            reason=None;side=signal['action']
            try:
                entry=n(signal['entry']);sl=n(signal['stop_loss']);tp=n(signal['take_profit'])
                if any(n(lot[k])<=0 for k in ('qty_step','min_qty','min_notional','max_leverage')):
                    raise ValueError('invalid instrument')
            except (ValueError,ArithmeticError,TypeError,KeyError):
                self.emit('SOURCE_REJECT',f'reject:{identity}',observed,dict(reason='INVALID_NUMERIC_SIGNAL_OR_INSTRUMENT'));return
            age=observed-int(signal['created_at'])
            if self.state['ended'] or self.state['entry_disabled']: reason='ENTRY_DISABLED'
            elif age<0 or age>self.rules['source_max_age_ms'] or int(signal['created_at'])<self.state['seed']['start']: reason='STALE_OR_PRE_REGISTRATION'
            elif side not in ('BUY','SELL') or not ((0<sl<entry<tp) if side=='BUY' else (0<tp<entry<sl)): reason='INVALID_PROTECTION'
            elif n(lot['max_leverage'])<n(self.rules['leverage']): reason='UNSUPPORTED_LEVERAGE'
            elif observed<self.state['cooldown_until']: reason='COOLDOWN'
            elif self.state['entries_today']>=6: reason='DAILY_TRADE_LIMIT'
            elif self.state['pending'] or any(a['position'] for a in self.state['arms'].values()): reason='PAIRED_SLOT_BUSY'
            elif any(a['invalid'] for a in self.state['arms'].values()): reason='INVALID_ARM'
            if self.state['funding_pending']: reason='FUNDING_UNRESOLVED'
            if reason: self.emit('SOURCE_REJECT',f'reject:{identity}',observed,dict(reason=reason));return
            self.state['pending']=dict(signal=signal,lot=lot,expires=int(signal['created_at'])+self.rules['pending_ttl_ms'],offered_at=observed)
    def equity(self,arm,quote):
        p=arm['position'];cash=n(arm['cash'])
        if p is None: return cash
        side=1 if p['side']=='BUY' else -1
        reference=n(quote['bid'] if side==1 else quote['ask'])
        exit_price=adverse_price(reference*(1-n(self.rules['slip'])*side),p['tick_size'],side==-1)
        return cash+n(p['qty'])*(exit_price-n(p['entry']))*side-n(p['qty'])*exit_price*n(self.rules['fee'])
    def exit(self,name,quote,observed,reason):
        arm=self.state['arms'][name];p=arm['position'];sign=1 if p['side']=='BUY' else -1
        reference=n(quote['bid'] if sign==1 else quote['ask'])
        price=adverse_price(reference*(1-n(self.rules['slip'])*sign),p['tick_size'],sign==-1)
        qty=n(p['qty']);fee=qty*price*n(self.rules['fee']);gross=qty*(price-n(p['entry']))*sign
        arm['cash']=text(n(arm['cash'])+gross-fee);arm['fees']=text(n(arm['fees'])+fee)
        trade=dict(source_id=p['source_id'],entered_at=p['entered_at'],exited_at=observed,side=p['side'],qty=p['qty'],
            entry=p['entry'],exit=text(price),gross_after_slippage=text(gross),fees=text(n(p['entry_fee'])+fee),
            net_before_funding=text(gross-n(p['entry_fee'])-fee),funding_unknown=p['funding_unknown'],reason=reason,
            strategy=p.get('strategy','selector'),funding_cost=p.get('funding_cost','0'))
        arm['trades'].append(trade);arm['position']=None
        self.state['cooldown_until']=max(self.state['cooldown_until'],observed+900000)
        self.emit('EXIT',f'exit:{name}:{p["source_id"]}',observed,dict(arm=name,reference=text(reference),quote_at=quote['at'],**trade))
    def quote(self,quote,observed):
        at=int(quote['at']);bid=n(quote['bid']);ask=n(quote['ask']);mark=n(quote['mark'])
        if not (0<bid<=ask and mark>0) or observed<at or observed-at>self.rules['quote_max_age_ms']:
            raise ValueError('invalid/stale quote')
        if at<self.state['last_quotes'].get(quote['symbol'],0) or observed<self.state['last_seen']:
            raise ValueError('out-of-order quote')
        with self.atomic():
            key=f'quote:{quote["symbol"]}:{at}'
            if not self.emit('QUOTE',key,at,quote): return
            self.state['last_quotes'][quote['symbol']]=at
            self.state['last_seen']=max(observed,self.state['last_seen'])
            if observed//86400000!=self.state['day']:
                self.state['day']=observed//86400000;self.state['day_halt']=False;self.state['entries_today']=0
                self.state['day_start']={name:arm['equity_liquidation'] for name,arm in self.state['arms'].items()}
                self.state['entry_disabled']=self.state['manual_pause'] or self.state['risk_halt']
            for name,arm in self.state['arms'].items():
                p=arm['position']
                if p is None or p['symbol']!=quote['symbol']: continue
                sign=1 if p['side']=='BUY' else -1;reference=bid if sign==1 else ask
                while at>=p['next_funding']:
                    event=f'{name}:{p["source_id"]}:{p["next_funding"]}'
                    if event not in self.state['funding_done']:
                        self.state['funding_pending'][event]=dict(arm=name,source_id=p['source_id'],at=p['next_funding'],
                            side=p['side'],qty=p['qty'],symbol=p['symbol'])
                        p['funding_unknown']=True
                    p['next_funding']+=p.get('funding_interval_ms',28800000)
                unrealized=n(p['qty'])*(mark-n(p['entry']))*sign
                margin=n(p['margin'])+unrealized-n(p['qty'])*mark*(n(p['maintenance'])+n(self.rules['fee']))
                if margin<=0:
                    if not arm['invalid']:
                        self.emit('MARGIN_FAILURE',f'margin:{name}:{p["source_id"]}',observed,dict(arm=name,quote_at=at))
                    arm['invalid']=True;self.state['entry_disabled']=True;self.state['risk_halt']=True
                    continue
                stop_hit=reference<=n(p['stop']) if sign==1 else reference>=n(p['stop'])
                tp_hit=reference>=n(p['tp']) if sign==1 else reference<=n(p['tp'])
                reason='OBSERVED_STOP' if stop_hit else 'OBSERVED_TP' if tp_hit else 'OBSERVED_TTL' if observed-p['entered_at']>=self.rules['holding_ttl_ms'] else None
                if reason: self.exit(name,quote,observed,reason);continue
            pending=self.state['pending']
            if pending and pending['signal']['symbol']==quote['symbol']:
                signal=pending['signal'];lot=pending['lot'];sign=1 if signal['action']=='BUY' else -1
                if observed>pending['expires']:
                    self.emit('PENDING_EXPIRED',f'expired:{signal["id"]}',observed,{});self.state['pending']=None
                elif not self.state['entry_disabled'] and not self.state['funding_pending']:
                    ref=ask if sign==1 else bid
                    fill=adverse_price(ref*(1+n(self.rules['slip'])*sign),lot.get('tick_size','.000000001'),sign==1)
                    limit=n(signal['entry'])
                    marketable=fill<=limit if sign==1 else fill>=limit
                    interval=int(lot.get('funding_interval_ms',28800000));next_fund=int(quote['next_funding'])
                    if min(abs(observed-next_fund),abs(observed-(next_fund-interval)))<30000:
                        marketable=False
                    if marketable and at>=pending['offered_at']:
                        cash=min(n(a['cash']) for a in self.state['arms'].values());distance=abs(fill-n(signal['stop_loss']))
                        worst_stop=adverse_price(n(signal['stop_loss'])*(1-n(self.rules['slip'])*sign),lot.get('tick_size','.000000001'),sign==-1)
                        risk=cash*n(self.rules['risk_fraction']);cost=abs(fill-worst_stop)+(fill+worst_stop)*n(self.rules['fee'])
                        if (fill-n(signal['stop_loss']))*sign<=0 or (n(signal['take_profit'])-fill)*sign<=0:
                            self.emit('ENTRY_REJECT',f'entry-reject:{signal["id"]}',observed,dict(reason='GAP_BEYOND_PROTECTION'));self.state['pending']=None
                        else:
                            qty=min(risk/cost,cash*n(self.rules['max_notional_ratio'])/fill)
                            qty=(qty/n(lot['qty_step'])).to_integral_value(rounding=ROUND_DOWN)*n(lot['qty_step'])
                            depth=n(quote['ask_size'] if sign==1 else quote['bid_size'])
                            fee=qty*fill*n(self.rules['fee']);margin=qty*fill/n(self.rules['leverage'])
                            buffer=fill*(1/n(self.rules['leverage'])-n(lot['maintenance'])-n(self.rules['fee']))
                            if qty<=0 or qty<n(lot['min_qty']) or qty*fill<n(lot['min_notional']) or qty>depth or margin+2*fee>cash or cost*n('1.5')>buffer:
                                self.emit('ENTRY_REJECT',f'entry-reject:{signal["id"]}',observed,dict(reason='SIZE_COST_MARGIN_OR_DEPTH'));self.state['pending']=None
                            else:
                                for name,arm in self.state['arms'].items():
                                    arm['cash']=text(n(arm['cash'])-fee);arm['fees']=text(n(arm['fees'])+fee)
                                    arm['position']=dict(symbol=signal['symbol'],source_id=signal['id'],side=signal['action'],
                                        qty=text(qty),entry=text(fill),entry_fee=text(fee),stop=str(signal['stop_loss']),tp=str(signal['take_profit']),
                                        initial_distance=text(distance),best_gain='0',entered_at=observed,next_funding=int(quote['next_funding']),
                                        funding_unknown=False,margin=text(margin),maintenance=lot['maintenance'],tick_size=lot.get('tick_size','.000000001'),
                                        funding_interval_ms=int(lot.get('funding_interval_ms',28800000)),funding_cost='0',strategy=signal.get('strategy','selector'))
                                    self.emit('ENTRY',f'entry:{name}:{signal["id"]}',observed,dict(arm=name,position=arm['position'],
                                        quote_at=at,reference=text(ref),modeled_loss_at_original_stop=text(qty*cost)))
                                self.state['pending']=None
                                self.state['entries_today']+=1
            for name,arm in self.state['arms'].items():
                if arm['position'] and arm['position']['symbol']!=quote['symbol']: continue
                value=self.equity(arm,quote);peak=max(n(arm['peak']),value)
                arm['equity_liquidation']=text(value);arm['mark_at']=observed
                arm['peak']=text(peak);arm['max_drawdown']=text(max(n(arm['max_drawdown']),1-value/peak))
                if n(arm['max_drawdown'])>=n(self.rules['max_drawdown']): self.state['risk_halt']=True
                if value<=n(self.state['day_start'][name])*n('.97'): self.state['day_halt']=True
            self.state['entry_disabled']=self.state['manual_pause'] or self.state['risk_halt'] or self.state['day_halt']

    def protect(self,quote,observed,asof):
        """Tighten using the observed quote at a fresh closed-five-minute decision.

        This never opens/exits a trade or invents a second quote timestamp.
        """
        if not (0<=observed-int(quote['at'])<=self.rules['quote_max_age_ms']) or int(quote['at'])<asof: return
        with self.atomic():
            arm=self.state['arms']['profit_protect'];p=arm['position']
            if not p or p['entered_at']>=asof or asof<=p.get('last_protection_asof',0): return
            p['last_protection_asof']=asof
            sign=1 if p['side']=='BUY' else -1;reference=n(quote['bid'] if sign==1 else quote['ask'])
            gain=(reference-n(p['entry']))*sign;distance=n(p['initial_distance'])
            p['best_gain']=text(max(n(p['best_gain']),gain));candidate=None
            if gain>=distance:
                cost=n(p['entry'])*(2*n(self.rules['fee'])+2*n(self.rules['slip']))
                candidate=n(p['entry'])+sign*cost
            if n(p['best_gain'])>=distance*n('1.5'):
                trailing=n(p['entry'])+sign*(n(p['best_gain'])-distance*n('.75'))
                candidate=trailing if candidate is None else max(candidate,trailing) if sign==1 else min(candidate,trailing)
            if candidate is not None and ((candidate>n(p['stop'])) if sign==1 else (candidate<n(p['stop']))):
                p['stop']=text(candidate)
                self.emit('STOP_UPDATE',f'stop:profit_protect:{p["source_id"]}:{asof}',observed,
                    dict(arm='profit_protect',stop=p['stop'],effective_after_quote=quote['at'],observed_at=observed,frame_asof=asof))

    def apply_funding(self,key,rate,mark,observed):
        with self.atomic():
            if key in self.state['funding_done']: return
            event=self.state['funding_pending'].get(key)
            if event is None: raise ValueError('unowned funding event')
            cost=n(event['qty'])*n(mark)*n(rate)*(1 if event['side']=='BUY' else -1)
            arm=self.state['arms'][event['arm']];arm['cash']=text(n(arm['cash'])-cost)
            arm['funding_cost']=text(n(arm['funding_cost'])+cost)
            arm['equity_liquidation']=text(n(arm['equity_liquidation'])-cost)
            arm['max_drawdown']=text(max(n(arm['max_drawdown']),1-n(arm['equity_liquidation'])/n(arm['peak'])))
            if n(arm['max_drawdown'])>=n(self.rules['max_drawdown']): self.state['risk_halt']=True
            if n(arm['equity_liquidation'])<=n(self.state['day_start'][event['arm']])*n('.97'): self.state['day_halt']=True
            self.state['entry_disabled']=self.state['manual_pause'] or self.state['risk_halt'] or self.state['day_halt']
            self.state['funding_done'].append(key);del self.state['funding_pending'][key]
            pending=any(e['arm']==event['arm'] and e['source_id']==event['source_id'] for e in self.state['funding_pending'].values())
            p=arm['position']
            if p and p['source_id']==event['source_id']:
                p['funding_cost']=text(n(p['funding_cost'])+cost);p['funding_unknown']=pending
            for trade in arm['trades']:
                if trade['source_id']==event['source_id']:
                    trade['funding_cost']=text(n(trade['funding_cost'])+cost);trade['funding_unknown']=pending
            self.emit('FUNDING',f'funding:{key}',observed,dict(**event,rate=str(rate),mark=str(mark),cost=text(cost),
                price_model='actual settled rate times settlement-minute mark open'))

    def control(self,identity,action,observed):
        with self.atomic():
            if self.state['last_control']==identity: return
            if action not in ('PAUSE','RESUME'): raise ValueError('unknown control')
            self.state['manual_pause']=action=='PAUSE';self.state['last_control']=identity
            self.state['entry_disabled']=self.state['manual_pause'] or self.state['risk_halt'] or self.state['day_halt']
            if self.state['entry_disabled']: self.state['pending']=None
            self.emit('CONTROL',f'control:{identity}',observed,dict(action=action))
    def finish(self,quotes,observed):
        if self.state['ended']: return
        with self.atomic():
            self.state['entry_disabled']=True;self.state['pending']=None
            for name,arm in self.state['arms'].items():
                p=arm['position']
                if p and p['symbol'] in quotes:
                    q=quotes[p['symbol']]
                    if 0<=observed-int(q['at'])<=self.rules['quote_max_age_ms']:
                        self.exit(name,q,observed,'PREDECLARED_TRIAL_END')
                        arm['equity_liquidation']=arm['cash'];arm['mark_at']=observed
            self.state['ended']=True
            self.emit('TRIAL_END','end',observed,dict(open_positions=sum(a['position'] is not None for a in self.state['arms'].values())))
    def report(self):
        summaries={}
        for name,arm in self.state['arms'].items():
            p=arm['position'];unknown=any(t['funding_unknown'] for t in arm['trades']) or bool(p and p['funding_unknown'])
            expected=n('20')+sum((n(t['net_before_funding']) for t in arm['trades']),D(0))-(n(p['entry_fee']) if p else 0)-n(arm['funding_cost'])
            summaries[name]=dict(ledger_cash_residual=text(n(arm['cash'])-expected),funding_complete_under_model=not unknown,
                modeled_net_pnl=text(n(arm['equity_liquidation'])-20) if not unknown and not arm['invalid'] else None)
        return dict(mode='LOCAL_QUOTE_PAPER',fingerprint=self.state['fingerprint'],rules=self.rules,
            seed=self.state['seed'],watermark=self.state['watermark'],pending=self.state['pending'],
            arms=self.state['arms'],entry_disabled=self.state['entry_disabled'],ended=self.state['ended'],
            last_seen=self.state['last_seen'],counts=dict(self.db.execute('select kind,count(*) from events group by kind')),
            actual_exchange_orders=0,profitability='NOT_ESTABLISHED',funding='UNKNOWN_IF_ANY_SETTLEMENT_CROSSED',
            accounting=summaries)
