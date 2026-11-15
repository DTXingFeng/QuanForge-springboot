import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paper_vnext_carry import CarryBook
from paper_vnext_ledger import n


class CarryTests(unittest.TestCase):
    def book(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        lot=dict(qty_step='.001',min_qty='.001',min_notional='5',spot_tick='.001',perp_tick='.001',maintenance='.005',funding_interval_ms=28800000)
        b=CarryBook(root/'paper.sqlite',dict(start=100000),lot);self.addCleanup(b.close);return b,root,lot
    def quotes(self,at,price='100',rate='.0001'):
        q=dict(at=at,bid=price,ask=price,bid_size='1000',ask_size='1000',symbol='XRPUSDT')
        return q,{**q,'mark':price,'next_funding':1000000 if at<1000000 else 29800000,'funding_rate':rate}
    def test_matching_legs_and_cash_survive_restart_without_duplicate_entry(self):
        b,root,lot=self.book();s,p=self.quotes(100010);b.observe(s,p,100020);q=b.state['position']['qty']
        self.assertGreater(float(q),0);self.assertEqual(b.accounting()['ledger_cash_residual'],'0')
        b.close();b=CarryBook(root/'paper.sqlite',dict(start=100000),lot);self.addCleanup(b.close)
        b.observe(s,p,100020);self.assertEqual(b.db.execute("select count(*) from events where kind='ENTRY'").fetchone()[0],1)
    def test_negative_funding_is_paid_and_cannot_be_duplicated(self):
        b,_,_=self.book();s,p=self.quotes(100010);b.observe(s,p,100020)
        s,p=self.quotes(1000010);b.observe(s,p,1000020);key=next(iter(b.state['funding_pending']))
        before=n(b.state['cash']);b.funding(key,'-.001','100',1000030);after=n(b.state['cash'])
        self.assertLess(after,before);b.funding(key,'-.001','100',1000030);self.assertEqual(n(b.state['cash']),after)
        self.assertEqual(b.accounting()['ledger_cash_residual'],'0')
    def test_gap_can_exhaust_short_margin_even_with_matched_spot(self):
        b,_,_=self.book();s,p=self.quotes(100010);b.observe(s,p,100020)
        s,p=self.quotes(100030,'300');b.observe(s,p,100040)
        self.assertTrue(b.state['invalid']);self.assertIsNone(b.accounting()['modeled_net_pnl'])
    def test_pause_keeps_position_managed_and_manual_close_preserves_costs(self):
        b,_,_=self.book();s,p=self.quotes(100010);b.observe(s,p,100020)
        b.control('pause','PAUSE',100025);self.assertIsNotNone(b.state['position'])
        b.control('close','CLOSE',100026);s,p=self.quotes(100030);b.observe(s,p,100040)
        self.assertIsNone(b.state['position']);self.assertEqual(len(b.state['trades']),1)
        self.assertLess(float(b.state['trades'][0]['net_pnl']),0);self.assertEqual(b.accounting()['ledger_cash_residual'],'0')
        b.state['risk_halt']=True;b.control('resume','RESUME',100050);s,p=self.quotes(5000000);b.observe(s,p,5000010)
        self.assertIsNone(b.state['position'])
    def test_stale_pair_and_nonpositive_funding_do_not_open(self):
        b,_,_=self.book();s,p=self.quotes(100010,rate='-.001');b.observe(s,p,100020)
        self.assertIsNone(b.state['position'])
        s,p=self.quotes(100030);s['at']=90000
        with self.assertRaises(ValueError):b.observe(s,p,100040)
    def test_manual_close_retries_after_insufficient_exit_depth(self):
        b,_,_=self.book();s,p=self.quotes(100010);b.observe(s,p,100020)
        b.control('close','CLOSE',100025);s,p=self.quotes(100030);s['bid_size']='0'
        b.observe(s,p,100040);self.assertIsNotNone(b.state['position'])
        s,p=self.quotes(100050);b.observe(s,p,100060)
        self.assertIsNone(b.state['position']);self.assertEqual(len(b.state['trades']),1)
    def test_out_of_order_response_cannot_change_position_or_cash(self):
        b,_,_=self.book();s,p=self.quotes(100050);b.observe(s,p,100060)
        before=(b.state['position'].copy(),b.state['cash']);s,p=self.quotes(100030)
        with self.assertRaises(ValueError):b.observe(s,p,100060)
        self.assertEqual((b.state['position'],b.state['cash']),before)
    def test_pending_negative_settlement_survives_restart_and_close(self):
        b,root,lot=self.book();s,p=self.quotes(100010);b.observe(s,p,100020)
        s,p=self.quotes(1000010);b.observe(s,p,1000020);key=next(iter(b.state['funding_pending']))
        b.close();b=CarryBook(root/'paper.sqlite',dict(start=100000),lot);self.addCleanup(b.close)
        b.control('close','CLOSE',1000025);s,p=self.quotes(1000030);b.observe(s,p,1000040)
        self.assertIsNone(b.state['trades'][0]['net_pnl'])
        b.funding(key,'-.001','100',1000050)
        self.assertLess(n(b.state['trades'][0]['net_pnl']),0)
        self.assertEqual(b.accounting()['ledger_cash_residual'],'0')
