"""Fail-closed release admission. No deployment, SSH, credentials or exchange writes."""
import argparse
import json
import time
from pathlib import Path

REQUIRED = (
    'local_tests_passed', 'artifact_verified', 'exact_account_mapping_verified',
    'java_account_flat_verified', 'shadow_account_flat_verified',
    'durable_exit_reconciliation_verified', 'full_trade_cost_ledger_verified',
    'shared_decision_snapshot_verified', 'exchange_protection_handover_verified',
)


def evaluate(evidence, now):
    blocked=[key for key in REQUIRED if evidence.get(key) is not True]
    observed=evidence.get('runtime_observed_ms')
    if not isinstance(observed,int) or observed>now or now-observed>300000:
        blocked.append('runtime_observation_missing_or_stale')
    candidate=evidence.get('candidate_sha256')
    if not isinstance(candidate,str) or len(candidate)!=64 or evidence.get('reviewed_candidate_sha256')!=candidate:
        blocked.append('exact_candidate_not_reviewed')
    return dict(ready_for_controlled_demo=not blocked,blocked=blocked,checked_ms=now,
                no_deployment_performed=True,no_exchange_orders_sent=True,
                note='Local tests and a flat Java account alone do not authorize unattended Demo.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    result=evaluate(json.loads(args.evidence.read_text(encoding='utf-8')),int(time.time()*1000))
    args.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['ready_for_controlled_demo'] else 2)
