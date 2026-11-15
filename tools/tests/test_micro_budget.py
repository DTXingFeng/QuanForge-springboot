import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from micro_budget_research import feasibility,expiry_screen
from crypto_edge_research import HOUR,DAY


class MicroBudgetTests(unittest.TestCase):
    def fixture(self,price='100'):
        p=dict(capital='20',feasibility_symbols=['TESTUSDT'],leverage_screen=[1,5,20,100,200],
            fees=dict(perp='.00055',slip='.0005'))
        snapshot=dict(server_time=48*HOUR,instruments={'TESTUSDT':{'linear':dict(
            lotSizeFilter=dict(qtyStep='.001',minOrderQty='.001',minNotionalValue='5'),
            leverageFilter=dict(maxLeverage='100'))}},linear_tickers=[dict(symbol='TESTUSDT',lastPrice=price)],
            recent_bars={'TESTUSDT':[[str(i*HOUR),price,str(float(price)*1.002),str(float(price)*.998),price,'1'] for i in range(48)]},
            risk_limits={'TESTUSDT':[dict(riskLimitValue='100000',maxLeverage='100',maintenanceMargin='.005')]})
        return snapshot,p

    def test_leverage_cannot_expand_risk_sized_exposure_or_bypass_exchange_cap(self):
        snapshot,p=self.fixture();rows=feasibility(snapshot,p)
        self.assertEqual(len({r['risk_sized_notional'] for r in rows}),1)
        self.assertTrue(rows[1]['passes_approximate_screen'])
        self.assertFalse(rows[3]['passes_approximate_screen'])
        self.assertIn('UNSUPPORTED_LEVERAGE',rows[4]['failures'])

    def test_contract_minimum_cannot_be_rounded_up_through_the_loss_budget(self):
        snapshot,p=self.fixture('100000');rows=feasibility(snapshot,p)
        self.assertTrue(all(not r['passes_approximate_screen'] for r in rows))
        self.assertTrue(all('BELOW_MINIMUM' in r['failures'] for r in rows))

    def test_expiry_screen_uses_sellable_bid_and_reserves_uncertain_settlement_fee(self):
        snapshot=dict(server_time=0,spot_tickers={'BTCUSDT':dict(ask1Price='100')},
            linear_tickers=[dict(symbol='BTCUSDT-EXP',bid1Price='101',lastPrice='110',deliveryFeeRate='0')],
            expiry_instruments=[dict(symbol='BTCUSDT-EXP',contractType='LinearFutures',settleCoin='USDT',
                baseCoin='BTC',deliveryTime=30*DAY,lotSizeFilter=dict(minOrderQty='.1'))])
        r=expiry_screen(snapshot,{})[0]
        self.assertEqual(r['raw_basis_pct'],'1')
        self.assertEqual(r['reserved_delivery_fee'],'0.0005')
        self.assertLess(float(r['indicative_net_per_spot_notional_pct']),1)
