"""Local-only event ledger and causal PAPER engine. No credentials or order API.

Decimal accounting; immutable events; atomic state/cursor; explicit unknown costs.
This is an isolated research companion, not a deployed Java/Bybit executor.
"""
import hashlib
import json
import math
import sqlite3
from decimal import Decimal
from pathlib import Path


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('nonfinite money')
    return result


def text(value):
    value = format(number(value), 'f')
    return value.rstrip('0').rstrip('.') if '.' in value else value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute('pragma journal_mode=WAL')
        self.db.executescript('''
            create table if not exists events(id text primary key, kind text not null,
                ts integer not null, payload text not null);
            create table if not exists state(id integer primary key check(id=1), payload text not null);
        ''')

    def close(self):
        self.db.close()

    def append(self, identity, kind, ts, payload):
        """Use within `with ledger.db:` for multi-event atomic state transitions."""
        encoded = canonical(payload)
        old = self.db.execute('select kind,ts,payload from events where id=?', (identity,)).fetchone()
        if old:
            if old != (kind, ts, encoded):
                raise ValueError('conflicting event identity: ' + identity)
            return False
        self.db.execute('insert into events values(?,?,?,?)', (identity, kind, ts, encoded))
        return True

    def events(self):
        return [(identity, kind, ts, json.loads(payload)) for identity, kind, ts, payload
                in self.db.execute('select * from events order by ts,id')]

    def trade(self, identity):
        events = [(kind, p) for _, kind, _, p in self.events() if p.get('trade') == identity]
        fills = [p for kind, p in events if kind == 'FILL']
        entries = [p for p in fills if p['role'] == 'ENTRY']
        exits = [p for p in fills if p['role'] == 'EXIT']
        qin = sum((number(p['qty']) for p in entries), Decimal(0))
        qout = sum((number(p['qty']) for p in exits), Decimal(0))
        closed = qin > 0 and qin == qout
        if qout > qin:
            raise ValueError('exit exceeds owned quantity')
        gross = None
        if closed:
            sign = 1 if entries[0]['side'] == 'BUY' else -1
            gross = sign * (sum((number(p['price']) * number(p['qty']) for p in exits), Decimal(0))
                            - sum((number(p['price']) * number(p['qty']) for p in entries), Decimal(0)))
        fees_known = all(p.get('fee') is not None for p in fills)
        fees = sum((number(p['fee']) for p in fills if p.get('fee') is not None), Decimal(0))
        funding = sum((number(p['cost']) for kind, p in events if kind == 'FUNDING'), Decimal(0))
        coverage = any(p.get('complete') is True for kind, p in events if kind == 'FUNDING_COVERAGE')
        before = gross - fees if closed and fees_known else None
        return dict(trade=identity, closed=closed, entry_qty=text(qin), exit_qty=text(qout),
                    gross=text(gross) if gross is not None else None, fees=text(fees),
                    fees_complete=fees_known, funding_observed=text(funding), funding_complete=coverage,
                    net_before_funding=text(before) if before is not None else None,
                    net=text(before - funding) if before is not None and coverage else None)

    def trades(self):
        ids = sorted({p['trade'] for _, kind, _, p in self.events() if kind == 'FILL'})
        return [self.trade(identity) for identity in ids]


def bars_snapshot(rows, interval, asof, max_age):
    """Closed bars only; normalize order, reject conflicting duplicates/gaps/stale tails."""
    unique = {}
    for raw in rows:
        bar = tuple(raw)
        ts = bar[0]
        if not isinstance(ts, int) or ts % interval or ts < 0:
            raise ValueError('unaligned timestamp')
        if len(bar) != 6 or not all(math.isfinite(float(x)) for x in bar):
            raise ValueError('invalid bar')
        _, o, h, low, c, v = bar
        if min(o, h, low, c) <= 0 or v < 0 or h < max(o, low, c) or low > min(o, h, c):
            raise ValueError('invalid OHLCV')
        if ts + interval > asof:
            continue
        if ts in unique and unique[ts] != bar:
            raise ValueError('conflicting bar')
        unique[ts] = bar
    bars = [unique[key] for key in sorted(unique)]
    if not bars or asof - bars[-1][0] - interval > max_age:
        raise ValueError('stale/absent bars')
    if any(b[0] - a[0] != interval for a, b in zip(bars, bars[1:])):
        raise ValueError('missing bars')
    digest = hashlib.sha256(canonical(bars).encode()).hexdigest()
    return bars, digest


def ema(values, period):
    result = values[0]
    for value in values[1:]:
        result += (value - result) * 2 / (period + 1)
    return result


class Paper:
    """One frozen rule, one symbol, one position. Signals use the next observed quote.

    Stop fills use adverse gap-open and slippage. Delayed backfill never creates
    new entries; existing holdings are reconstructed and marked as delayed.
    Funding is deliberately unknown until explicit coverage evidence is supplied.
    """
    def __init__(self, ledger, config, now):
        self.ledger, self.config = ledger, config
        config_hash = hashlib.sha256(canonical(config).encode()).hexdigest()
        saved = ledger.db.execute('select payload from state where id=1').fetchone()
        if saved:
            self.state = json.loads(saved[0])
            if self.state['config_hash'] != config_hash:
                raise ValueError('frozen experiment config changed')
        else:
            self.state = dict(config_hash=config_hash, start=now, cursor=None, bars=[], pending=None,
                              position=None, cash=config['initial_equity'], peak=config['initial_equity'],
                              max_drawdown='0', halted=False, day=now//86400000, day_start=config['initial_equity'])
            with ledger.db:
                ledger.append('experiment', 'EXPERIMENT', now, dict(config=config, config_hash=config_hash))
                self.save()

    def save(self):
        self.ledger.db.execute('insert into state values(1,?) on conflict(id) do update set payload=excluded.payload',
                               (canonical(self.state),))

    def process(self, rows, now):
        import copy
        cfg, state = self.config, self.state
        interval = cfg['interval_ms']
        bars, digest = bars_snapshot(rows, interval, now, cfg['max_age_ms'])
        saved_bars = {b[0]: tuple(b) for b in state['bars']}
        if any(b[0] in saved_bars and b != saved_bars[b[0]] for b in bars):
            raise ValueError('previously consumed bar revised')
        if state['cursor'] is None:
            if len(bars) < cfg['warmup']:
                raise ValueError('insufficient warmup')
            # Do not turn the pre-registration history into forward trades.
            with self.ledger.db:
                state['bars'] = bars[-cfg['warmup']:]
                state['cursor'] = bars[-1][0]
                self.ledger.append('warmup', 'WARMUP', now, dict(asof=now, hash=digest, count=len(bars)))
                self.save()
            return
        unseen = [b for b in bars if b[0] > state['cursor']]
        if unseen and unseen[0][0] != state['cursor'] + interval:
            raise ValueError('cursor gap; bounded backfill required')
        for bar in unseen:
            before = copy.deepcopy(state)
            try:
                with self.ledger.db:
                    # The frame and signal are linked; actual observation time is separate.
                    self.step(bar, now, now - (bar[0] + interval) > cfg['decision_ttl_ms'])
                    state['cursor'] = bar[0]
                    self.save()
            except Exception:
                self.state = state = before
                raise

    def event(self, kind, ts, payload, suffix=''):
        self.ledger.append(f'{kind}:{ts}:{suffix}', kind, ts, payload)

    def observe_quote(self, price, quote_at, observed):
        """Only this live/explicitly replayed quote path can open risk; never use a later candle open."""
        import copy
        cfg, state = self.config, self.state
        if observed < quote_at or observed - quote_at > cfg['quote_ttl_ms'] or number(price) <= 0:
            raise ValueError('stale/invalid quote')
        before = copy.deepcopy(state)
        try:
            with self.ledger.db:
                if not self.ledger.append(f'quote:{quote_at}', 'QUOTE', quote_at, dict(price=text(price))):
                    return
                p = state['position']
                if p and ((number(price) <= number(p['stop'])) if p['side']=='BUY' else (number(price) >= number(p['stop']))):
                    self.exit(price, observed, observed, 'OBSERVED_QUOTE_SL')
                self.mark(price, observed, observed, 'quote')
                pending = state['pending']
                state['pending'] = None
                if pending:
                    age = observed - pending['asof']
                    if age < 0 or age > cfg['decision_ttl_ms'] or age > cfg['interval_ms']:
                        self.event('REJECT', observed, dict(reason='expired decision', asof=pending['asof']))
                    else:
                        p = state['position']
                        if p and p['side'] != pending['side']:
                            self.exit(price, observed, observed, 'OBSERVED_QUOTE_REVERSE')
                        if not state['position'] and not state['halted']:
                            cash = number(state['cash'])
                            distance = number(pending['atr']) * number(cfg['stop_atr'])
                            if cash <= 0 or distance <= 0:
                                raise ValueError('invalid sizing')
                            estimate = number(price) * (1 + number(cfg['slippage_rate']))
                            cap = cash * number(cfg['max_notional_ratio']) / (estimate * (1 + number(cfg['fee_rate'])))
                            qty = min(cash * number(cfg['risk_fraction']) / distance, cap)
                            trade = f'{cfg["symbol"]}:{observed}'
                            entry, fee = self.fill('ENTRY', pending['side'], qty, price, observed, observed, trade, 'EMA_CROSS')
                            state['cash'] = text(cash - fee)
                            stop = entry - distance if pending['side']=='BUY' else entry + distance
                            if stop <= 0:
                                raise ValueError('invalid stop')
                            state['position'] = dict(trade=trade, qty=text(qty), entry=text(entry), side=pending['side'],
                                                     stop=text(stop), stop_effective=observed, entered=observed)
                            self.event('STOP_SET', observed, dict(trade=trade, stop=text(stop), effective_at=observed,
                                                                 decision_asof=pending['asof'], input_hash=pending['input_hash']))
                self.mark(price, observed, observed, 'quote-after')
                self.save()
        except Exception:
            self.state = before
            raise

    def fill(self, role, side, qty, reference, ts, observed, trade, reason):
        price = number(reference) * (1 + number(self.config['slippage_rate']) * (1 if side == 'BUY' else -1))
        fee = price * qty * number(self.config['fee_rate'])
        self.event('FILL', ts, dict(trade=trade, role=role, side=side, qty=text(qty), price=text(price),
                   reference=text(reference), fee=text(fee), cost_model='ASSUMED', observed_at=observed,
                   reason=reason, effective_at=ts), role)
        return price, fee

    def exit(self, reference, ts, observed, reason):
        state = self.state
        p = state['position']
        qty, entry = number(p['qty']), number(p['entry'])
        price, fee = self.fill('EXIT', 'SELL' if p['side'] == 'BUY' else 'BUY', qty,
                               reference, ts, observed, p['trade'], reason)
        gross = (price - entry) * qty * (1 if p['side'] == 'BUY' else -1)
        state['cash'] = text(number(state['cash']) + gross - fee)
        state['position'] = None

    def step(self, bar, observed, delayed):
        cfg, state = self.config, self.state
        ts, o, h, low, close, _ = bar
        end = ts + cfg['interval_ms']
        snapshot_hash = hashlib.sha256(canonical(state['bars']).encode()).hexdigest()
        self.event('BAR', ts, dict(bar=bar, observed_at=observed, delayed=delayed))
        # Entries are executed only by observe_quote at actual observation time.
        state['pending'] = None
        p = state['position']
        if p:
            stop = number(p['stop'])
            hit = number(low) <= stop if p['side'] == 'BUY' else number(h) >= stop
            if hit:
                # A full OHLC contains pre-entry extrema when entry is inside this bar.
                # Charging a stop is conservative, never proof of actual intrabar ordering.
                reference = min(number(o), stop) if p['side'] == 'BUY' else max(number(o), stop)
                self.exit(reference, end, observed, 'SL_OHLC_TIME_UNKNOWN')
            elif end - p['entered'] >= cfg['ttl_bars'] * cfg['interval_ms']:
                self.exit(close, end, observed, 'TTL')
        history = state['bars'] + [bar]
        history = history[-cfg['warmup']:]
        closes = [b[4] for b in history]
        fast, slow = cfg['fast'], cfg['slow']
        previous = ema(closes[:-1], fast) - ema(closes[:-1], slow)
        current = ema(closes, fast) - ema(closes, slow)
        side = 'BUY' if previous <= 0 < current else 'SELL' if previous >= 0 > current else None
        trs = [max(b[2]-b[3], abs(b[2]-a[4]), abs(b[3]-a[4])) for a, b in zip(history, history[1:])]
        atr = sum(trs[-14:]) / 14
        self.event('SIGNAL', end, dict(side=side, asof=end, input_hash=hashlib.sha256(canonical(history).encode()).hexdigest(),
                   previous_input_hash=snapshot_hash, atr=atr, delayed=delayed, observed_at=observed))
        state['bars'] = history
        if side and not delayed:
            state['pending'] = dict(side=side, asof=end, atr=str(atr), input_hash=hashlib.sha256(canonical(history).encode()).hexdigest())
        self.mark(close, end, observed, 'bar')

    def mark(self, price, at, observed, source):
        cfg, state = self.config, self.state
        p = state['position']
        unrealized = ((number(price)-number(p['entry'])) * number(p['qty']) * (1 if p['side']=='BUY' else -1)) if p else Decimal(0)
        marked = number(state['cash']) + unrealized
        day = at // 86400000
        if day != state['day']:
            state['day'], state['day_start'] = day, state.get('last_mark', state['cash'])
        state['last_mark'] = text(marked)
        state['peak'] = text(max(number(state['peak']), marked))
        dd = 1 - marked / number(state['peak'])
        state['max_drawdown'] = text(max(number(state['max_drawdown']), dd))
        if dd >= number(cfg['max_drawdown']) or marked <= number(state['day_start']) * (1-number(cfg['daily_loss_limit'])):
            state['halted'] = True
            state['pending'] = None
        self.event('MARK', at, dict(cash=state['cash'], unrealized=text(unrealized),
                   equity_before_funding=text(marked), funding_complete=False,
                   drawdown_before_funding=text(dd), halted=state['halted'], observed_at=observed), source)

    def report(self):
        events = self.ledger.events()
        trades = self.ledger.trades()
        fills = [p for _, k, _, p in events if k == 'FILL']
        marks = [p for _, k, _, p in events if k == 'MARK']
        return dict(mode='LOCAL_PAPER', complete_net_performance=False, funding='UNKNOWN',
                    config_hash=self.state['config_hash'], cursor=self.state['cursor'],
                    entries=sum(p['role']=='ENTRY' for p in fills), closed=sum(t['closed'] for t in trades),
                    fees_assumed=text(sum((number(p['fee']) for p in fills),Decimal(0))),
                    net_equity=None, equity_before_funding=marks[-1]['equity_before_funding'] if marks else self.state['cash'],
                    max_drawdown_before_funding=self.state['max_drawdown'],
                    position=self.state['position'], halted=self.state['halted'],
                    delayed_bars=sum(k=='BAR' and p['delayed'] for _, k, _, p in events),
                    trades=trades)
