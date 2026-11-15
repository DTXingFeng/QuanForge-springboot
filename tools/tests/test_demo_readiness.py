import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from demo_readiness import evaluate, REQUIRED


class ReadinessTests(unittest.TestCase):
    def evidence(self):
        return dict({key:True for key in REQUIRED},runtime_observed_ms=1000,candidate_sha256='a'*64,reviewed_candidate_sha256='a'*64)

    def test_missing_unknown_and_string_true_fail_closed(self):
        for value in [None,False,'true',1]:
            row=self.evidence();row['shadow_account_flat_verified']=value
            self.assertFalse(evaluate(row,2000)['ready_for_controlled_demo'])
        self.assertFalse(evaluate({},2000)['ready_for_controlled_demo'])

    def test_stale_observation_or_different_binary_blocks_release(self):
        row=self.evidence();self.assertFalse(evaluate(row,400000)['ready_for_controlled_demo'])
        row['reviewed_candidate_sha256']='b'*64
        self.assertFalse(evaluate(row,2000)['ready_for_controlled_demo'])

    def test_all_synthetic_proofs_are_required(self):
        row=self.evidence();self.assertTrue(evaluate(row,2000)['ready_for_controlled_demo'])
        for key in REQUIRED:
            changed=dict(row);del changed[key]
            self.assertFalse(evaluate(changed,2000)['ready_for_controlled_demo'])
