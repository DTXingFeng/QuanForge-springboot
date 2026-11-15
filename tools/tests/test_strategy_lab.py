import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strategy_lab import signals,replay,INTERVAL,number


class StrategyLabTests(unittest.TestCase):
    def test_drawdown_halt_is_from_equity_peak_even_while_total_profit_is_positive(self):
        raw=[(0,100.,101.,99.,100.,1.),(INTERVAL,100.,501.,99.,500.,1.),
             (2*INTERVAL,330.,331.,329.,330.,1.)]
        result=replay(raw,[('BUY',10.),(None,10.),(None,10.)],{}, {},0,3*INTERVAL,'0','0')
        self.assertGreater(number(result['return_pct']),0)
        self.assertGreater(number(result['close_sampled_max_drawdown_pct']),10)
        self.assertTrue(result['hard_drawdown_halt'])
    def test_signal_uses_next_open_and_gap_stop_uses_worse_price(self):
        raw=[(0,100.,101.,99.,100.,1.),(INTERVAL,110.,111.,109.,110.,1.),
             (2*INTERVAL,100.,101.,99.,100.,1.)]
        result=replay(raw,[('BUY',1.),(None,1.),(None,1.)],{}, {},0,3*INTERVAL,'0','0')
        self.assertEqual(result['entry_events'][0]['at'],INTERVAL)
        self.assertEqual(result['entry_events'][0]['price'],'110')
        self.assertEqual(result['trades'][0]['exit'],'100')
        self.assertEqual(number(result['accounting_residual']),0)

    def test_funding_payment_and_receipt_have_opposite_signs(self):
        raw=[(i*INTERVAL,100.,101.,99.,100.,1.) for i in range(4)]
        for side,expected_sign in [('BUY',1),('SELL',-1)]:
            result=replay(raw,[(side,1.)]+[(None,1.)]*3,{2*INTERVAL:'0.001'},
                          {2*INTERVAL:'100'},0,4*INTERVAL,'0','0')
            self.assertGreater(number(result['funding_cost_signed'])*expected_sign,0)
            self.assertEqual(number(result['accounting_residual']),0)

    def test_daily_risk_stop_stays_latched_after_existing_position_recovers(self):
        raw=[(i*INTERVAL,100.,101.,99.,100.,1.) for i in range(3)]
        raw += [(3*INTERVAL,100.,161.,99.,160.,1.),(4*INTERVAL,160.,161.,159.,160.,1.)]
        result=replay(raw,[('BUY',1.),(None,1.),(None,1.),('SELL',1.),(None,1.)],
                      {2*INTERVAL:'0.1'},{2*INTERVAL:'100'},0,5*INTERVAL,'0','0')
        self.assertEqual(result['entries'],1)
        self.assertFalse(result['hard_drawdown_halt'])

    def test_cash_control_and_costs_cannot_create_profit(self):
        raw=[(i*INTERVAL,100.,101.,99.,100.,1.) for i in range(4)]
        flat=replay(raw,[(None,1.)]*4,{}, {},0,4*INTERVAL,'0.00055','0.0005')
        self.assertEqual(flat['entries'],0);self.assertEqual(flat['final_equity'],'200')
        traded=replay(raw,[('BUY',1.)]+[(None,1.)]*3,{}, {},0,4*INTERVAL,'0.00055','0.0005')
        self.assertLess(number(traded['final_equity']),200)
        self.assertGreater(number(traded['fees']),0)
    def test_appending_future_crash_does_not_change_past_signals(self):
        bars=[(i*900000,100.,101.,99.,100.+(i%9)/10,1.) for i in range(250)]
        for name in ['ema_cross','breakout','mean_reversion','cash']:
            a=signals(bars,name)
            b=signals(bars+[(250*900000,100.,101.,1.,2.,1.)],name)
            self.assertEqual(a,b[:len(a)])
