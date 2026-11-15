import sys
import unittest
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paper_vnext_strategy import decide,INTERVAL,HOUR
from paper_vnext_ledger import PaperBook


class PaperVnextStrategyTests(unittest.TestCase):
    def test_future_candles_cannot_change_a_past_decision(self):
        bars=[[i*INTERVAL,100,101,99,100,1] for i in range(3100)]
        asof=3000*INTERVAL
        before=decide(bars[:3000],asof)
        for b in bars[3000:]: b[1:5]=[10000,20000,1,15000]
        self.assertEqual(before,decide(bars,asof))

    def test_missing_and_conflicting_closed_candles_reject_the_frame(self):
        bars=[[i*INTERVAL,100,101,99,100,1] for i in range(3000)]
        with self.assertRaises(ValueError): decide(bars[:100]+bars[101:],3000*INTERVAL)
        with self.assertRaises(ValueError): decide(bars+[[0,100,102,99,100,1]],3000*INTERVAL)

    def test_funding_after_exit_is_posted_once_and_cash_reconciles(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        t=PaperBook(root/'paper.sqlite',dict(start=100000,watermark=1));self.addCleanup(t.close)
        lot=dict(qty_step='.01',min_qty='.01',min_notional='5',max_leverage='100',maintenance='.005',funding_interval_ms=28800000)
        signal=dict(id=2,symbol='TESTUSDT',action='BUY',entry='100',stop_loss='98',take_profit='106',created_at=100000)
        t.offer(signal,lot,100010)
        def quote(at,price,next_funding):
            t.quote(dict(symbol='TESTUSDT',at=at,bid=price,ask=price,mark=price,bid_size='100',ask_size='100',next_funding=next_funding),at+10)
        quote(100020,'99.9',1000000)
        quote(1000010,'95',29800000)
        self.assertEqual(len(t.state['funding_pending']),2)
        for key in list(t.state['funding_pending']):
            t.apply_funding(key,'.001','100',1000020);t.apply_funding(key,'.001','100',1000020)
        self.assertFalse(t.state['funding_pending'])
        self.assertEqual(sum(e['kind']=='FUNDING' for e in t.events()),2)
        self.assertTrue(all(a['ledger_cash_residual']=='0' for a in t.report()['accounting'].values()))
        self.assertTrue(all(a['modeled_net_pnl'] is not None for a in t.report()['accounting'].values()))

    def test_resume_does_not_clear_a_latched_risk_stop(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        t=PaperBook(root/'paper.sqlite',dict(start=100000,watermark=1));self.addCleanup(t.close)
        with t.atomic(): t.state['risk_halt']=True;t.state['entry_disabled']=True
        t.control('operator','RESUME',100010)
        self.assertTrue(t.state['entry_disabled'])
