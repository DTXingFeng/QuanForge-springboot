import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audit_strategy_failures import excursions,INTERVAL


class FailureDiagnosisTests(unittest.TestCase):
    def test_stop_bar_does_not_invent_profit_before_exit(self):
        bars=[(0,100,200,50,100,1)]
        row=excursions(bars,dict(entered=0,exited=INTERVAL,entry='100',side='BUY',reason='SL_INTRABAR_TIME_UNKNOWN'),1)
        self.assertEqual(row['covered_full_bars'],0);self.assertIsNone(row['mfe_r'])

    def test_only_prior_full_bars_count_and_short_sign_is_correct(self):
        bars=[(0,100,101,98,100,1),(INTERVAL,100,200,50,100,1)]
        row=excursions(bars,dict(entered=0,exited=2*INTERVAL,entry='100',side='SELL',reason='SL_INTRABAR_TIME_UNKNOWN'),1)
        self.assertEqual(row['mfe_r'],2);self.assertEqual(row['mae_r'],1)
