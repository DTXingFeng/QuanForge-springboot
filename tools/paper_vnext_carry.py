"""Cash-funded spot/perpetual PAPER pair. Quotes only; no order/network interface.

One equal-coin pair, full initial short cash reserve, actual settled funding-rate
receipts, explicit mark-price proxy, atomic SQLite state and immutable events.
"""
import copy
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from paper_vnext_strategy import canonical,VERSION
from paper_vnext_ledger import n,text,adverse_price,D,ROUND_DOWN


class CarryBook:
    def __init__(self,path,seed,lot):
        self.db=sqlite3.connect(path,timeout=5);self.db.execute('pragma journal_mode=WAL')
        self.db.executescript('create table if not exists state(id integer primary key check(id=1),payload text);'
            'create table if not exists events(id text primary key,kind text,at integer,payload text);')
        self.rules=dict(capital='20',spot_fee='.001',perp_fee='.00055',slip='.0005',max_drawdown='.03',
            minimum_short_equity_fraction='.25',quote_max_age_ms=15000,pair_max_skew_ms=3000,cooldown_ms=3600000,
            leverage='1',strategy='SPOT_LONG_EQUAL_COIN_PERP_SHORT',paper_passed=False)
        self.lot=lot;fingerprint=hashlib.sha256((canonical([seed,lot,self.rules])+Path(__file__).read_text()).encode()).hexdigest()
        row=self.db.execute('select payload from state').fetchone()
        if row:
            self.state=json.loads(row[0])
            if self.state['fingerprint']!=fingerprint:raise ValueError('frozen carry experiment changed')
        else:
            self.state=dict(fingerprint=fingerprint,seed=seed,cash='20',position=None,fees='0',funding_income='0',realized_price_pnl='0',
                equity='20',peak='20',max_drawdown='0',manual_pause=False,risk_halt=False,invalid=False,
                funding_pending={},funding_done=[],trades=[],last_times=[0,0],last_control=None,cooldown_until=0,
                last_seen=seed['start'],entry_reject=None)
            with self.atomic():self.emit('REGISTRATION','registration',seed['start'],dict(seed=seed,lot=lot,rules=self.rules))
    @contextmanager
    def atomic(self):
        before=copy.deepcopy(self.state)
        try:
            with self.db:
                yield
                self.db.execute('insert into state values(1,?) on conflict(id) do update set payload=excluded.payload',(canonical(self.state),))
        except Exception:self.state=before;raise
    def emit(self,kind,key,at,payload):
        encoded=canonical(payload);old=self.db.execute('select kind,at,payload from events where id=?',(key,)).fetchone()
        if old:
            if old!=(kind,at,encoded):raise ValueError('conflicting immutable receipt')
            return False
        self.db.execute('insert into events values(?,?,?,?)',(key,kind,at,encoded));return True
    def error(self,at,stage,error):
        with self.atomic():self.emit('POLL_ERROR',f'error:{stage}:{at}',at,dict(stage=stage,type=type(error).__name__))
    def fills(self,spot,perp,opening):
        slip=n(self.rules['slip'])
        sx=adverse_price(n(spot['ask' if opening else 'bid'])*(1+slip if opening else 1-slip),self.lot['spot_tick'],opening)
        px=adverse_price(n(perp['bid' if opening else 'ask'])*(1-slip if opening else 1+slip),self.lot['perp_tick'],not opening)
        return sx,px
    def nav(self,spot,perp):
        p=self.state['position']
        if not p:return n(self.state['cash'])
        sx,px=self.fills(spot,perp,False);q=n(p['qty'])
        return n(self.state['cash'])+q*sx+q*(n(p['perp_entry'])-px)-q*(sx*n(self.rules['spot_fee'])+px*n(self.rules['perp_fee']))
    def close_pair(self,spot,perp,at,reason):
        p=self.state['position'];q=n(p['qty'])
        if q>min(n(spot['bid_size']),n(perp['ask_size'])):
            self.state['entry_reject']='EXIT_DEPTH_INSUFFICIENT';return
        sx,px=self.fills(spot,perp,False);paid=q*(sx*n(self.rules['spot_fee'])+px*n(self.rules['perp_fee']))
        pnl=q*(sx-n(p['spot_entry'])+n(p['perp_entry'])-px)
        self.state['cash']=text(n(self.state['cash'])+q*sx+q*(n(p['perp_entry'])-px)-paid)
        self.state['fees']=text(n(self.state['fees'])+paid);self.state['realized_price_pnl']=text(n(self.state['realized_price_pnl'])+pnl)
        pending=any(e['trade_id']==p['id'] for e in self.state['funding_pending'].values())
        trade=dict(id=p['id'],entered_at=p['entered_at'],exited_at=at,side='HEDGE',qty=p['qty'],entry=p['spot_entry'],exit=text(sx),
            spot_entry=p['spot_entry'],perp_entry=p['perp_entry'],spot_exit=text(sx),perp_exit=text(px),
            price_pnl_after_slippage=text(pnl),fees=text(n(p['entry_fees'])+paid),funding_income=p['funding_income'],
            net_pnl=None if pending else text(pnl+n(p['funding_income'])-n(p['entry_fees'])-paid),reason=reason)
        self.state['trades'].append(trade);self.state['position']=None;self.state['cooldown_until']=at+self.rules['cooldown_ms']
        self.emit('EXIT',f'exit:{p["id"]}',at,trade)
    def observe(self,spot,perp,at):
        times=[int(spot['at']),int(perp['at'])]
        if abs(times[0]-times[1])>self.rules['pair_max_skew_ms'] or any(at<t or at-t>self.rules['quote_max_age_ms'] for t in times):
            raise ValueError('stale/asynchronous pair')
        for quote in [spot,perp]:
            if not 0<n(quote['bid'])<=n(quote['ask']):raise ValueError('invalid bid/ask')
        if any(t<old for t,old in zip(times,self.state['last_times'])):raise ValueError('out-of-order pair')
        with self.atomic():
            if not self.emit('QUOTE',f'pair:{times[0]}:{times[1]}',max(times),dict(spot=spot,perp=perp)):return
            self.state['last_times']=times;self.state['last_seen']=at;p=self.state['position']
            if p:
                while times[1]>=p['next_funding']:
                    key=f'{p["id"]}:{p["next_funding"]}'
                    if key not in self.state['funding_done']:
                        self.state['funding_pending'][key]=dict(trade_id=p['id'],at=p['next_funding'],qty=p['qty'],symbol='XRPUSDT')
                    p['next_funding']+=self.lot['funding_interval_ms']
                q=n(p['qty']);mark=n(perp['mark'])
                short_equity=n(self.state['cash'])+q*(n(p['perp_entry'])-mark)
                if short_equity<=q*mark*(n(self.lot['maintenance'])+n(self.rules['perp_fee'])):
                    if not self.state['invalid']:self.emit('MARGIN_FAILURE',f'margin:{p["id"]}',at,dict(short_equity=text(short_equity)))
                    self.state['invalid']=True;self.state['risk_halt']=True
                elif short_equity/(q*mark)<n(self.rules['minimum_short_equity_fraction']):
                    self.state['risk_halt']=True;self.close_pair(spot,perp,at,'MARGIN_BUFFER')
                elif self.state['risk_halt'] and not self.state['invalid']:
                    self.close_pair(spot,perp,at,'RISK_CLOSE_PENDING')
                elif self.state.get('close_requested'):
                    self.close_pair(spot,perp,at,'MANUAL_PAPER_CLOSE')
                    self.state['close_requested']=self.state['position'] is not None
            value=self.nav(spot,perp);self.state['equity']=text(value);self.state['peak']=text(max(n(self.state['peak']),value))
            self.state['max_drawdown']=text(max(n(self.state['max_drawdown']),1-value/n(self.state['peak'])))
            if n(self.state['max_drawdown'])>=n(self.rules['max_drawdown']):
                self.state['risk_halt']=True
                if self.state['position'] and not self.state['invalid']:self.close_pair(spot,perp,at,'DRAWDOWN_STOP')
            if not self.state['position'] and not self.state['manual_pause'] and not self.state['risk_halt'] and not self.state['funding_pending'] and at>=self.state['cooldown_until']:
                sx,px=self.fills(spot,perp,True);cash=n(self.state['cash'])
                q=cash/(sx*(1+n(self.rules['spot_fee']))+px*(1+n(self.rules['perp_fee'])))
                q=(q/n(self.lot['qty_step'])).to_integral_value(rounding=ROUND_DOWN)*n(self.lot['qty_step'])
                reason=None
                if perp.get('funding_rate') is None:reason='FUNDING_UNKNOWN'
                elif n(perp['funding_rate'])<=0:reason='WAIT_POSITIVE_FUNDING'
                elif q<=0 or q<n(self.lot['min_qty']) or min(q*sx,q*px)<n(self.lot['min_notional']):reason='BELOW_MINIMUM'
                elif q>min(n(spot['ask_size']),n(perp['bid_size'])):reason='INSUFFICIENT_DEPTH'
                elif min(abs(n(perp['next_funding'])-at),abs(n(perp['next_funding'])-self.lot['funding_interval_ms']-at))<30000:reason='SETTLEMENT_BOUNDARY'
                if reason:self.state['entry_reject']=reason
                else:
                    paid=q*(sx*n(self.rules['spot_fee'])+px*n(self.rules['perp_fee']))
                    self.state['cash']=text(cash-q*sx-paid);self.state['fees']=text(n(self.state['fees'])+paid)
                    self.state['position']=dict(id=at,kind='HEDGE',symbol='XRPUSDT',side='HEDGE',qty=text(q),
                        spot_entry=text(sx),perp_entry=text(px),entered_at=at,next_funding=int(perp['next_funding']),
                        entry_fees=text(paid),funding_income='0',initial_notional=text(q*(sx+px)))
                    self.state['entry_reject']=None
                    self.emit('ENTRY',f'entry:{at}',at,copy.deepcopy(self.state['position']))
            self.state['equity']=text(self.nav(spot,perp))
            self.state['max_drawdown']=text(max(n(self.state['max_drawdown']),1-n(self.state['equity'])/n(self.state['peak'])))
    def funding(self,key,rate,mark,at):
        with self.atomic():
            if key in self.state['funding_done']:return
            e=self.state['funding_pending'][key];income=n(e['qty'])*n(mark)*n(rate)
            self.state['cash']=text(n(self.state['cash'])+income);self.state['equity']=text(n(self.state['equity'])+income)
            self.state['funding_income']=text(n(self.state['funding_income'])+income)
            self.state['funding_done'].append(key);del self.state['funding_pending'][key]
            p=self.state['position']
            if p and p['id']==e['trade_id']:p['funding_income']=text(n(p['funding_income'])+income)
            for trade in self.state['trades']:
                if trade['id']==e['trade_id']:
                    trade['funding_income']=text(n(trade['funding_income'])+income)
                    trade['net_pnl']=None if any(x['trade_id']==e['trade_id'] for x in self.state['funding_pending'].values()) else text(n(trade['price_pnl_after_slippage'])+n(trade['funding_income'])-n(trade['fees']))
            self.emit('FUNDING',f'funding:{key}',at,dict(**e,rate=str(rate),mark=str(mark),income=text(income),price_model='settlement-minute mark open'))
    def control(self,identity,action,at):
        with self.atomic():
            if identity==self.state['last_control']:return
            if action not in ('PAUSE','RESUME','CLOSE'):raise ValueError('invalid control')
            self.state['manual_pause']=action!='RESUME';self.state['last_control']=identity
            if action=='CLOSE':self.state['close_requested']=bool(self.state['position'])
            elif action=='RESUME' and not self.state['position']:self.state['close_requested']=False
            self.emit('CONTROL',f'control:{identity}',at,dict(action=action))
    def accounting(self):
        p=self.state['position'];expected=n('20')+n(self.state['realized_price_pnl'])-n(self.state['fees'])+n(self.state['funding_income'])
        if p:expected-=n(p['qty'])*n(p['spot_entry'])
        residual=n(self.state['cash'])-expected
        return dict(ledger_cash_residual=text(residual),funding_complete_under_model=not self.state['funding_pending'],
            modeled_net_pnl=text(n(self.state['equity'])-20) if not self.state['funding_pending'] and not self.state['invalid'] and residual==0 else None)
    def close(self):self.db.close()
