import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verified_paper import Ledger, Paper, bars_snapshot
from run_verified_paper import calibrate_clock, public_get


def config():
    return dict(symbol='BTCUSDT', interval_ms=900000, max_age_ms=990000, decision_ttl_ms=90000,
                quote_ttl_ms=15000, warmup=64, fast=3, slow=6, initial_equity='200',
                fee_rate='0.00055', slippage_rate='0.0005', risk_fraction='0.01',
                max_notional_ratio='1', stop_atr='1.2', ttl_bars=96,
                max_drawdown='0.10', daily_loss_limit='0.03')


def bars(n=64):
    return [(i*900000,100.,101.,99.,100.,1.) for i in range(n)]


class LedgerTests(unittest.TestCase):
    def test_costs_and_unknown_funding_are_not_hidden(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = Ledger(Path(folder) / 'ledger.sqlite')
            ledger.append('entry', 'FILL', 1, {'trade': 't', 'role': 'ENTRY', 'side': 'BUY',
                          'qty': '2', 'price': '100', 'fee': '0.11'})
            ledger.append('exit', 'FILL', 2, {'trade': 't', 'role': 'EXIT', 'side': 'SELL',
                          'qty': '2', 'price': '105', 'fee': '0.1155'})
            row = ledger.trade('t')
            self.assertEqual(row['gross'], '10')
            self.assertEqual(row['fees'], '0.2255')
            self.assertEqual(row['net_before_funding'], '9.7745')
            self.assertIsNone(row['net'])
            ledger.append('coverage', 'FUNDING_COVERAGE', 2, {'trade': 't', 'complete': True})
            self.assertEqual(ledger.trade('t')['net'], '9.7745')
            ledger.close()

    def test_duplicate_events_are_idempotent_but_conflicts_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'ledger.sqlite')
            with ledger.db:
                self.assertTrue(ledger.append('e','FUNDING',1,dict(trade='t',cost='-0.3')))
                self.assertFalse(ledger.append('e','FUNDING',1,dict(trade='t',cost='-0.3')))
            with self.assertRaises(ValueError):
                ledger.append('e','FUNDING',1,dict(trade='t',cost='0.3'))
            self.assertEqual(ledger.trade('t')['funding_observed'],'-0.3')
            ledger.close()

    def test_missing_fee_and_partial_exit_cannot_be_full_net(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'ledger.sqlite')
            ledger.append('e','FILL',1,dict(trade='t',role='ENTRY',side='BUY',qty='2',price='100',fee=None))
            ledger.append('x','FILL',2,dict(trade='t',role='EXIT',side='SELL',qty='1',price='105',fee='0.1'))
            row=ledger.trade('t')
            self.assertFalse(row['closed']); self.assertIsNone(row['net'])
            self.assertFalse(row['fees_complete'])
            ledger.close()


class MarketTests(unittest.TestCase):
    def test_clock_calibration_is_independent_and_rejects_large_skew(self):
        with patch('run_verified_paper.time.time',side_effect=[1000.,1000.2]), patch('run_verified_paper.public_get',return_value={'result':{'timeNano':'1001100000000'}}):
            calibration=calibrate_clock()
            self.assertEqual(calibration['offset_ms'],1000)
            self.assertEqual(calibration['uncertainty_ms'],100)
        with patch('run_verified_paper.time.time',side_effect=[1000.,1000.2]), patch('run_verified_paper.public_get',return_value={'result':{'timeNano':'2001100000000'}}):
            with self.assertRaises(ValueError):calibrate_clock()

    def test_order_endpoint_cannot_be_used_by_forward_runner(self):
        with self.assertRaises(ValueError):public_get('/v5/order/create',{})
    def test_order_duplicates_and_unclosed_bar(self):
        raw=bars(65)
        result,_=bars_snapshot(list(reversed(raw))+[raw[1]],900000,64*900000,990000)
        self.assertEqual(result,bars())

    def test_gaps_conflicts_bad_alignment_and_stale_data(self):
        raw=bars()
        cases=[raw[:20]+raw[21:],raw+[tuple([raw[0][0],100.,102.,99.,100.,1.])],
               [(1,100.,101.,99.,100.,1.)]+raw[1:]]
        for case in cases:
            with self.subTest(case=case[0]), self.assertRaises(ValueError):
                bars_snapshot(case,900000,64*900000,990000)
        with self.assertRaises(ValueError):
            bars_snapshot(raw,900000,70*900000,990000)


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'paper.sqlite'
        self.ledger=Ledger(self.path)
        self.start=64*900000
        self.engine=Paper(self.ledger,config(),self.start)
        self.engine.process(bars(),self.start)

    def tearDown(self):
        self.ledger.close(); self.temp.cleanup()

    def signal(self, down=False):
        raw=bars()+[(self.start,100.,101. if down else 111.,89. if down else 99.,90. if down else 110.,1.)]
        self.engine.process(raw,self.start+900000)
        return raw

    def test_warmup_does_not_fabricate_entries_and_quote_is_not_backdated(self):
        self.assertEqual(self.engine.report()['entries'],0)
        self.signal()
        self.assertEqual(self.engine.report()['entries'],0)
        now=self.start+900000+1000
        self.engine.observe_quote('110',now,now)
        fills=[(ts,p) for _,k,ts,p in self.ledger.events() if k=='FILL']
        self.assertEqual(len(fills),1); self.assertEqual(fills[0][0],now)
        self.assertLessEqual(float(fills[0][1]['qty'])*float(fills[0][1]['price']),200.)
        self.assertIsNone(self.engine.report()['net_equity'])

    def test_restart_duplicate_quote_no_second_position(self):
        self.signal(); now=self.start+900000+1000
        self.ledger.close(); self.ledger=Ledger(self.path)
        self.engine=Paper(self.ledger,config(),now)
        self.engine.observe_quote('110',now,now)
        self.engine.observe_quote('110',now,now)
        self.assertEqual(self.engine.report()['entries'],1)

    def test_stale_signal_or_quote_never_opens(self):
        self.signal()
        now=self.start+900000+100000
        with self.assertRaises(ValueError):
            self.engine.observe_quote('110',now-16000,now)
        self.engine.observe_quote('110',now,now)
        self.assertEqual(self.engine.report()['entries'],0)

    def test_gap_keeps_position_and_quote_protection_still_works(self):
        raw=self.signal(); now=self.start+900000+1000
        self.engine.observe_quote('110',now,now)
        with self.assertRaises(ValueError):
            self.engine.process(raw+[(self.start+2700000,100.,101.,99.,100.,1.)],self.start+3600000)
        self.assertIsNotNone(self.engine.state['position'])
        self.engine.observe_quote('90',now+1000,now+1000)
        self.assertIsNone(self.engine.state['position'])
        self.assertEqual(self.engine.report()['closed'],1)

    def test_future_bar_or_revised_history_cannot_change_decision(self):
        raw=self.signal()
        cursor=self.engine.state['cursor']
        future=raw+[(self.start+900000,110.,999.,1.,500.,1.)]
        self.engine.process(future,self.start+900000)
        self.assertEqual(self.engine.state['cursor'],cursor)
        raw[1]=(900000,100.,102.,99.,100.,1.)
        with self.assertRaises(ValueError):self.engine.process(raw,self.start+900000)

    def test_changed_config_is_rejected(self):
        changed=config(); changed['fee_rate']='0'
        with self.assertRaises(ValueError):Paper(self.ledger,changed,self.start)

    def test_database_failure_rolls_back_events_and_memory(self):
        self.signal(); now=self.start+900000+1000
        original=self.engine.state.copy()
        with self.ledger.db:
            self.ledger.db.execute("create trigger fail_state before update on state begin select raise(ABORT,'disk fault'); end")
        with self.assertRaises(Exception):self.engine.observe_quote('110',now,now)
        self.assertEqual(self.engine.state,original)
        self.assertEqual(self.engine.report()['entries'],0)

    def test_short_quote_stop_has_correct_sign_and_halted_state_keeps_exits(self):
        self.signal(down=True); now=self.start+900000+1000
        self.engine.observe_quote('90',now,now)
        self.engine.state['halted']=True
        self.engine.observe_quote('110',now+1000,now+1000)
        row=self.ledger.trades()[0]
        self.assertTrue(row['closed']); self.assertLess(float(row['gross']),0)


if __name__ == '__main__':
    unittest.main()
