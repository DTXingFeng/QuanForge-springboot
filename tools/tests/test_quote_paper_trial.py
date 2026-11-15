import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quote_paper_trial import Trial


class QuotePaperTrialTests(unittest.TestCase):
    def trial(self):
        directory=Path(self.enterContext(tempfile.TemporaryDirectory()))
        trial=Trial(directory/'trial.sqlite',{'start':100000,'watermark':1})
        self.addCleanup(trial.close)
        return trial

    def test_failed_public_attempt_budget_survives_restart(self):
        from run_quote_paper_trial import Public
        directory=Path(self.enterContext(tempfile.TemporaryDirectory()))
        client=Public(directory);opener=Mock();opener.open.side_effect=TimeoutError()
        with patch('run_quote_paper_trial.urllib.request.build_opener',return_value=opener):
            with self.assertRaises(TimeoutError): client.get('/v5/market/time')
        self.assertEqual(Public(directory).count,1)

    def test_invalid_ai_output_is_quarantined_once(self):
        t=self.trial()
        signal=dict(id=2,symbol='TESTUSDT',action='BUY',entry='100',stop_loss=None,take_profit='104',created_at=100000)
        lot=dict(qty_step='.01',min_qty='.01',min_notional='5',max_leverage='100',maintenance='.005')
        t.offer(signal,lot,100010)
        self.assertIsNone(t.state['pending'])
        self.assertEqual(t.state['watermark'],2)
        self.assertEqual(sum(e['kind']=='SOURCE_REJECT' for e in t.events()),1)

    def test_out_of_order_quote_cannot_execute_a_stop_created_in_its_future(self):
        t=self.trial()
        signal=dict(id=2,symbol='TESTUSDT',action='BUY',entry='100',stop_loss='98',take_profit='106',created_at=100000)
        lot=dict(qty_step='.01',min_qty='.01',min_notional='5',max_leverage='100',maintenance='.005')
        t.offer(signal,lot,100010)
        def q(at,bid,ask):
            return dict(symbol='TESTUSDT',at=at,bid=bid,ask=ask,mark=bid,bid_size='100',ask_size='100',next_funding=10000000)
        t.quote(q(100020,'99.89','99.90'),100030)
        t.quote(q(100050,'103','103.01'),100060)
        with self.assertRaisesRegex(ValueError,'out.of.order'):
            t.quote(q(100040,'99','99.01'),100070)
        self.assertIsNotNone(t.state['arms']['profit_protect']['position'])

    def test_gap_stop_uses_observed_bid_and_unknown_funding_stays_unknown(self):
        t=self.trial()
        lot=dict(qty_step='.01',min_qty='.01',min_notional='5',max_leverage='100',maintenance='.005')
        t.offer(dict(id=2,symbol='TESTUSDT',action='BUY',entry='100',stop_loss='98',take_profit='106',created_at=100000),lot,100010)
        def q(at,bid,ask):
            return dict(symbol='TESTUSDT',at=at,bid=bid,ask=ask,mark=bid,bid_size='100',ask_size='100',next_funding=100035)
        t.quote(q(100020,'99.89','99.90'),100030)
        t.quote(q(100040,'95','95.01'),100050)
        for a in t.state['arms'].values():
            self.assertLess(float(a['trades'][0]['exit']),95)
            self.assertTrue(a['trades'][0]['funding_unknown'])
        self.assertTrue(all(a['modeled_net_pnl'] is None for a in t.report()['accounting'].values()))
        self.assertTrue(all(a['ledger_cash_residual']=='0' for a in t.report()['accounting'].values()))

    def test_past_registration_and_below_minimum_do_not_create_trades(self):
        t=self.trial()
        lot=dict(qty_step='100',min_qty='100',min_notional='5',max_leverage='100',maintenance='.005')
        signal=dict(id=2,symbol='TESTUSDT',action='BUY',entry='100',stop_loss='98',take_profit='106',created_at=99999)
        t.offer(signal,lot,100010);self.assertIsNone(t.state['pending'])
        signal.update(id=3,created_at=100000);t.offer(signal,lot,100010)
        t.quote(dict(symbol='TESTUSDT',at=100020,bid='99.89',ask='99.9',mark='100',bid_size='100',ask_size='100',next_funding=10000000),100030)
        self.assertEqual(sum(e['kind']=='ENTRY' for e in t.events()),0)
        self.assertEqual(sum(e['kind']=='ENTRY_REJECT' for e in t.events()),1)

    def test_margin_failure_invalidates_result_and_does_not_duplicate_failure(self):
        t=self.trial();lot=dict(qty_step='.01',min_qty='.01',min_notional='5',max_leverage='100',maintenance='.005')
        t.offer(dict(id=2,symbol='TESTUSDT',action='BUY',entry='100',stop_loss='98',take_profit='106',created_at=100000),lot,100010)
        for at,price in [(100020,'99.9'),(100040,'70'),(100060,'60')]:
            t.quote(dict(symbol='TESTUSDT',at=at,bid=price,ask=price,mark=price,bid_size='100',ask_size='100',next_funding=10000000),at+10)
        self.assertEqual(sum(e['kind']=='MARGIN_FAILURE' for e in t.events()),2)
        self.assertTrue(all(a['modeled_net_pnl'] is None for a in t.report()['accounting'].values()))

    def test_sell_limit_does_not_fill_below_limit_and_restart_cannot_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'trial.sqlite';t=Trial(db,{'start':100000,'watermark':1})
            signal=dict(id=2,symbol='TESTUSDT',action='SELL',entry='100',stop_loss='102',take_profit='96',created_at=100000)
            lot=dict(qty_step='.01',min_qty='.01',min_notional='5',max_leverage='100',maintenance='.005')
            t.offer(signal,lot,100010)
            t.quote(dict(symbol='TESTUSDT',at=100020,bid='99',ask='99.01',mark='99',bid_size='100',ask_size='100',next_funding=10000000),100030)
            self.assertTrue(all(a['position'] is None for a in t.state['arms'].values()))
            q=dict(symbol='TESTUSDT',at=100040,bid='100.1',ask='100.11',mark='100.1',bid_size='100',ask_size='100',next_funding=10000000)
            t.quote(q,100050)
            self.assertTrue(all(a['position'] is not None for a in t.state['arms'].values()))
            t.close();t=Trial(db,{'start':100000,'watermark':1});t.quote(q,100050)
            self.assertEqual(sum(e['kind']=='ENTRY' for e in t.events()),2)
            t.close()

    def test_profit_protection_is_set_after_observed_profit_and_exits_on_later_quote(self):
        with tempfile.TemporaryDirectory() as d:
            t=Trial(Path(d)/'trial.sqlite',{'start':100000,'watermark':1})
            signal=dict(id=2,symbol='TESTUSDT',action='BUY',entry='100',stop_loss='98',take_profit='106',created_at=100000)
            lot=dict(qty_step='.01',min_qty='.01',min_notional='5',max_leverage='100',maintenance='.005')
            t.offer(signal,lot,100010)
            def q(at,bid,ask):
                t.quote(dict(symbol='TESTUSDT',at=at,bid=bid,ask=ask,mark=bid,bid_size='100',ask_size='100',next_funding=10000000),at+10)
            q(100020,'99.89','99.90');q(100030,'103','103.01')
            self.assertIsNotNone(t.state['arms']['profit_protect']['position'])
            q(100040,'101.7','101.71');q(100050,'101','101.01')
            self.assertIsNone(t.state['arms']['profit_protect']['position'])
            self.assertIsNotNone(t.state['arms']['source_exit']['position'])
            trade=t.state['arms']['profit_protect']['trades'][0]
            self.assertGreater(float(trade['net_before_funding']),0)
            t.close()
