import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crypto_edge_research import carry, daily_signals, DAY


class CryptoEdgeTests(unittest.TestCase):
    def test_hedge_cancels_equal_spot_perp_moves_and_earns_only_funding(self):
        spot=[(0,100,101,99,100,1),(DAY,110,111,109,110,1)]
        marks=[(0,100,101,99,100,0),(DAY,110,111,109,110,0)]
        result=carry(spot,spot,marks,{DAY:'0.001'},0,2*DAY,'0','0','0','0.001','0','0')
        self.assertGreater(float(result['funding_income']),0)
        self.assertEqual(result['basis_pnl_before_costs'],'0')
        self.assertAlmostEqual(float(result['net_pnl']),float(result['funding_income']))

    def test_negative_funding_is_paid_and_four_leg_costs_are_charged(self):
        bars=[(0,100,101,99,100,1),(DAY,100,101,99,100,1)]
        r=carry(bars,bars,bars,{DAY:'-0.001'},0,2*DAY,'.001','.00055','.0005','.001','0','0')
        self.assertLess(float(r['funding_income']),0)
        self.assertGreater(float(r['fees']),0)
        self.assertGreater(float(r['slippage_diagnostic']),0)
        self.assertAlmostEqual(float(r['net_pnl']),float(r['funding_income'])-float(r['fees'])-float(r['slippage_diagnostic']))

    def test_hedged_nav_does_not_prevent_short_margin_failure(self):
        bars=[(0,100,100,100,100,1),(DAY,300,310,299,300,1)]
        r=carry(bars,bars,bars,{},0,2*DAY,'0','0','0','.001','0','0')
        self.assertEqual(r['status'],'RESERVE_EXHAUSTED')
        self.assertIsNone(r['return_pct'])
        self.assertEqual(r['counterfactual_return_pct'],'0')

    def test_future_prices_cannot_change_past_signals(self):
        bars=[(i*DAY,100,101,99,100+i,1) for i in range(260)]
        prior=daily_signals(bars[:240],'sma200')
        bars[240:]=[(b[0],1,1,1,1,1) for b in bars[240:]]
        self.assertEqual(prior,daily_signals(bars,'sma200')[:240])

    def test_spot_signal_executes_next_open_and_cash_is_a_real_control(self):
        from crypto_edge_research import spot_replay
        bars=[(i*DAY,100,101,99,100,1) for i in range(5)]
        signals=[False,True,False,False,False]
        r=spot_replay(bars,signals,DAY,4*DAY,'0','0','.001','0','0')
        self.assertEqual(r['events'][0]['at'],2*DAY)
        self.assertEqual(r['events'][0]['signal_at'],DAY)
        self.assertEqual(r['return_pct'],'0')
        cash=spot_replay(bars,[False]*5,DAY,4*DAY,'.001','.0005','.001','0','0')
        self.assertEqual(cash['orders'],0)
        self.assertEqual(cash['return_pct'],'0')

    def test_missing_funding_mark_fails_instead_of_assuming_zero(self):
        bars=[(0,100,101,99,100,1),(DAY,100,101,99,100,1)]
        with self.assertRaisesRegex(ValueError,'funding mark missing'):
            carry(bars,bars,bars,{DAY+123:'0.001'},0,2*DAY,'0','0','0','.001','0','0')
