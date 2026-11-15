import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audit_cashflows import reconcile


def row(identity,ts,change,balance,kind='TRADE'):
    return dict(id=identity,transactionTime=str(ts),currency='USDT',change=str(change),cashBalance=str(balance),
                cashFlow=str(change),funding='0',fee='0',type=kind)


class CashflowTests(unittest.TestCase):
    def test_timestamp_ties_are_linked_by_balances_and_transfers_excluded_from_performance(self):
        rows=[row('b',1,-2,198),row('a',1,200,200,'TRANSFER_IN'),row('c',2,3,201)]
        report=reconcile(rows+[rows[0]])
        self.assertTrue(report['recorded_balance_chain_reconciled'])
        self.assertEqual(report['transfers_net'],'200')
        self.assertEqual(report['change_excluding_transfers'],'1')
        self.assertIsNone(report['account_rate_of_return'])

    def test_omitted_transfer_and_wrong_fee_identity_cannot_reconcile(self):
        rows=[row('a',1,-2,198),row('b',2,3,301)]
        report=reconcile(rows)
        self.assertFalse(report['recorded_balance_chain_reconciled'])
        self.assertEqual(report['balance_gaps'][0]['unexplained'],'100')
        rows[0]['fee']='1'
        self.assertEqual(reconcile(rows)['row_equation_violations'],1)

    def test_conflicting_duplicates_or_currency_rejected(self):
        with self.assertRaises(ValueError):reconcile([row('a',1,1,1),row('a',1,2,2)])
        r=row('a',1,1,1);r['currency']='BTC'
        with self.assertRaises(ValueError):reconcile([r])
