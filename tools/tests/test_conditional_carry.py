import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conditional_carry import entry_decision,HOUR


class ConditionalCarryTests(unittest.TestCase):
    def test_cost_hurdle_uses_only_published_past_rates(self):
        rates={i*8*HOUR:'0.0001' for i in range(21)}
        asof=161*HOUR
        base=entry_decision(rates,asof,'.001','.00055','.0005')
        self.assertTrue(base['enter'])
        # A known positive regime is insufficient when round-trip costs double.
        self.assertFalse(entry_decision(rates,asof,'.002','.0011','.001')['enter'])
        rates[asof+7*HOUR]='-0.1'
        self.assertEqual(base,entry_decision(rates,asof,'.001','.00055','.0005'))

    def test_reversal_exits_after_publication_and_execution_delay(self):
        from conditional_carry import replay
        bars=[[i*HOUR,'100','100','100','100','1'] for i in range(300)]
        rates={i*HOUR:'.0001' if i<200 else '-.00001' for i in range(0,300,8)}
        r=replay(bars,bars,bars,rates,0,300*HOUR,'conditional')
        self.assertEqual(r['entries'],1)
        self.assertEqual(r['closed_trades'][0]['reason'],'FUNDING_REVERSED')
        self.assertEqual(r['closed_trades'][0]['exit_at'],218*HOUR)
        self.assertEqual(r['closed_trades'][0]['decision_asof'],217*HOUR)
        self.assertEqual(r['ledger_residual'],'0')

    def test_gap_can_exhaust_margin_before_a_planned_exit(self):
        from conditional_carry import replay
        bars=[[i*HOUR,*(['100']*4),'1'] for i in range(300)]
        for i in range(218,300): bars[i]=[i*HOUR,*(['300']*4),'1']
        rates={i*HOUR:'.0001' if i<200 else '-.00001' for i in range(0,300,8)}
        r=replay(bars,bars,bars,rates,0,300*HOUR,'conditional')
        self.assertEqual(r['status'],'RESERVE_EXHAUSTED')
        self.assertIsNone(r['return_pct'])

    def test_missing_funding_and_duplicate_bars_cannot_be_treated_as_normal(self):
        from conditional_carry import replay
        bars=[[i*HOUR,*(['100']*4),'1'] for i in range(24)]
        rates={0:'.0001',8*HOUR:'.0001',16*HOUR:'.0001'}
        with self.assertRaises(ValueError):
            replay(bars+[bars[-1]],bars,bars,rates,0,24*HOUR,'static')
        with self.assertRaises(ValueError):
            replay(bars,bars,bars,{0:'.0001'},0,24*HOUR,'static')

    def test_future_price_changes_do_not_rewrite_prior_orders(self):
        from conditional_carry import replay
        bars=[[i*HOUR,*(['100']*4),'1'] for i in range(300)]
        rates={i*HOUR:'.0001' for i in range(0,300,8)}
        prefix=replay(bars[:230],bars[:230],bars[:230],rates,0,230*HOUR,'conditional')
        for i in range(230,300): bars[i]=[i*HOUR,*(['10000']*4),'1']
        whole=replay(bars,bars,bars,rates,0,300*HOUR,'conditional')
        self.assertEqual([o for o in prefix['orders'] if o['at']<230*HOUR],
                         [o for o in whole['orders'] if o['at']<230*HOUR])

    def test_small_account_cannot_invent_fractional_contracts(self):
        from conditional_carry import replay
        bars=[[i*HOUR,*(['200000']*4),'1'] for i in range(24)]
        rates={i*HOUR:'.0001' for i in range(0,24,8)}
        r=replay(bars,bars,bars,rates,0,24*HOUR,'static',qty_step='.001')
        self.assertEqual(r['entries'],0)
        self.assertEqual(r['blocked_minimum'],1)
        self.assertEqual(r['return_pct'],'0')

    def test_common_price_move_is_hedged_and_all_four_fees_are_paid(self):
        from conditional_carry import replay
        bars=[[i*HOUR,*([str(100+i)]*4),'1'] for i in range(24)]
        rates={i*HOUR:'.0001' for i in range(0,24,8)}
        r=replay(bars,bars,bars,rates,0,24*HOUR,'static')
        self.assertEqual(r['ledger_residual'],'0')
        self.assertEqual(r['leg_orders'],4)
        self.assertGreater(float(r['fees']),0)
        self.assertAlmostEqual(float(r['price_pnl_after_slippage']),-float(r['slippage_diagnostic']))

    def test_entry_boundary_does_not_receive_already_settled_funding(self):
        from conditional_carry import replay
        bars=[[i*HOUR,*(['100']*4),'1'] for i in range(24)]
        rates={0:'.5',8*HOUR:'.0001',16*HOUR:'.0001'}
        r=replay(bars,bars,bars,rates,0,24*HOUR,'static',spot_fee='0',perp_fee='0',slip='0')
        self.assertEqual(r['funding_income'],'0.02')
        self.assertEqual(r['net_pnl'],'0.02')
