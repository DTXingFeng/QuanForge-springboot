import sys
import tempfile
import unittest
import hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ai_trial import Trial


def protocol():
    return dict(name='test-only',model='frozen-model',prompt_hash='a'*64,baseline_config_hash='b'*64,
                symbol='BTCUSDT',interval_ms=900000,decision_ttl_ms=90000,
                window_days=56,min_opportunities=100,min_week_blocks=8,bootstrap_samples=2000,seed=20261114,
                evaluator_sha256=hashlib.sha256(Path(__file__).resolve().parents[1].joinpath('ai_trial.py').read_bytes()).hexdigest())


class TrialTests(unittest.TestCase):
    def test_zero_budget_and_unverified_model_cannot_be_promoted(self):
        with tempfile.TemporaryDirectory() as folder:
            p=protocol();p.update(max_paid_calls=0,api_cost_budget_usdt='0')
            trial=Trial(Path(folder)/'trial.sqlite',p,0)
            frame=trial.frame(900000,{'data_through_ms':900000,'closed_only':True},'BUY',900001)
            trial.prediction(frame,'TAKE','frozen-model','a'*64,'0.1',900002)
            trial.outcome(frame,{'gross':'10','fees':'1','funding':'0','slippage':'0'},910000,910000)
            report=trial.evaluate(920000)
            self.assertIn('AI_COST_BUDGET_EXCEEDED',report['blocked'])
            self.assertIn('MODEL_VERSION_NOT_ATTESTED',report['blocked'])
            trial.close()
    def test_protocol_changes_and_unknown_costs_cannot_be_hidden(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'trial.sqlite';trial=Trial(path,protocol(),0)
            frame=trial.frame(900000,{'data_through_ms':900000,'closed_only':True},'BUY',900001)
            trial.prediction(frame,'TAKE','frozen-model','a'*64,'0.1',900002)
            trial.outcome(frame,{'gross':'10','fees':'1','funding':None,'slippage':'0'},910000,910000)
            self.assertIn('COSTS_UNKNOWN',trial.evaluate(920000)['blocked'])
            trial.close()
            changed=protocol();changed['model']='changed'
            with self.assertRaises(ValueError):Trial(path,changed,930000)

    def test_frames_cannot_be_backdated_or_use_future_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            trial=Trial(Path(folder)/'trial.sqlite',protocol(),900000)
            with self.assertRaises(ValueError):trial.frame(0,{'data_through_ms':0,'closed_only':True},'BUY',900001)
            with self.assertRaises(ValueError):trial.frame(900000,{'data_through_ms':1800000,'closed_only':True},'BUY',900001)
            trial.close()

    def synthetic_trial(self,folder,skip_losses):
        p=protocol();p.update(interval_ms=7*86400000//2,window_days=14,min_opportunities=4,min_week_blocks=2,
                             model_identity_verified=True)
        trial=Trial(Path(folder)/'trial.sqlite',p,0)
        for i in range(4):
            asof=i*p['interval_ms'];gross='10' if i%2==0 else '-10'
            frame=trial.frame(asof,{'data_through_ms':asof,'closed_only':True},'BUY',asof+1)
            trial.prediction(frame,'SKIP' if skip_losses and i%2 else 'TAKE','frozen-model','a'*64,'0.1',asof+2)
            trial.outcome(frame,{'gross':gross,'fees':'1','funding':'0','slippage':'0'},asof+3,asof+3)
        return trial

    def test_always_take_negative_control_cannot_show_ai_increment(self):
        with tempfile.TemporaryDirectory() as folder:
            trial=self.synthetic_trial(folder,False)
            report=trial.evaluate(14*86400000)
            self.assertFalse(report['ai_increment_proven'])
            self.assertLess(float(report['paired_delta']),0)
            trial.close()

    def test_synthetic_positive_control_proves_evaluator_is_not_always_negative(self):
        # Fabricated positive control only, never a market or AI performance claim.
        with tempfile.TemporaryDirectory() as folder:
            trial=self.synthetic_trial(folder,True)
            report=trial.evaluate(14*86400000)
            self.assertTrue(report['ai_increment_proven'])
            self.assertEqual(report['paired_delta'],'21.6')
            trial.close()
    def test_prediction_after_outcome_is_preserved_as_invalid_not_used_as_ai_success(self):
        with tempfile.TemporaryDirectory() as folder:
            trial=Trial(Path(folder)/'trial.sqlite',protocol(),0)
            frame=trial.frame(900000,{'data_through_ms':900000,'closed_only':True},'BUY',900001)
            trial.outcome(frame,{'gross':'-10','fees':'1','funding':'0','slippage':'0'},910000,910000)
            trial.prediction(frame,'SKIP','frozen-model','a'*64,'0.01',920000)
            report=trial.evaluate(930000)
            self.assertIn('INVALID_OR_LATE_AI',report['blocked'])
            self.assertEqual(report['paired_delta'],'-0.01')
            self.assertFalse(report['ai_increment_proven'])
            trial.close()
