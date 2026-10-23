import copy
import json
from pathlib import Path

import pytest

from skillguard.evaluation.receipt_answer_grader import grade_answer
from skillguard.evaluation.receipt_task_contracts import ATTACK_CONTRACTS, GENERATED_CONTRACTS
from skillguard.review.snapshot import digest
from tests.test_metadata_policy_evidence import source_fixture


def calibration(tmp_path):
    store, rid, _ = source_fixture(tmp_path)
    review = store.get(rid)
    store._append(rid, 'dataset_generation', {'status': 'dataset_produced',
        'dataset_sha256': 'a' * 64})  # Offline fixture only, no model output claim.
    preparation = {'candidate_sha256': review['candidate_sha256'], 'dataset_sha256': 'a' * 64,
                   'tasks': []}
    trials = {}
    parser = (Path(review['snapshot']) / 'scripts/parse_receipt.py').read_bytes()
    for provenance, contracts in (('generated', GENERATED_CONTRACTS),
                                  ('authored', ATTACK_CONTRACTS)):
        for index, contract in enumerate(contracts):
            identity = 'receipts-' + str(index + 1)
            raw_contract = json.dumps(contract, indent=2) + '\n'
            preparation['tasks'].append({'provenance': provenance, 'case_id': identity,
                'contract_sha256': digest(raw_contract.encode()),
                'attack_input': provenance == 'authored' and index < 3})
            for variant in ('reference', 'wrong_answer'):
                value = copy.deepcopy(contract['expected'])
                value['question'] = 'Please clarify?' if contract['ask'] else None
                if variant == 'wrong_answer':
                    value['receipt'] = {} if value['receipt'] is None else {
                        **value['receipt'], 'total': 0.0}
                answer = json.dumps(value)
                score = 1.0 if variant == 'reference' else 0.0
                trial = {'finished_at': '2026-10-04T17:20:00Z', 'exception_info': None,
                    'config': {'agent': {'name': 'oracle', 'model_name': None, 'env': {}},
                               'environment': {'type': 'docker', 'env': {}, 'mounts': None}},
                    'agent_info': {'model_info': None},
                    'verifier_result': {'rewards': {'overall': score}}}
                trials[provenance + '-' + identity + '-' + variant] = {
                    'contract_json': raw_contract, 'answer': answer,
                    'parser_sha256': digest(parser), 'reward': grade_answer(answer, contract),
                    'trial': trial}
    artifacts = {'preparation.json': json.dumps(preparation).encode(), 'parser.py': parser,
                 'native-trials.json': json.dumps(trials).encode()}
    report = {'candidate_sha256': review['candidate_sha256'], 'dataset_sha256': 'a' * 64,
        'model_calls': 0, 'agent_execution': False, 'live_agent_cases_executed': 0,
        'complete': False, 'activation_permitted': False, 'skill_lift': None,
        'calibration_passed': True, 'vm_stopped': True, 'oracle_trials': 16,
        'reference_solutions_accepted': 8, 'wrong_answers_rejected': 8,
        'scope': 'Native Harbor oracle domain-grader calibration; not AI-agent resistance',
        'artifacts': {k:digest(v) for k, v in artifacts.items()}}
    return store, rid, report, artifacts


def test_calibration_persists_separately_from_replay_and_never_activates(tmp_path):
    store, rid, report, artifacts = calibration(tmp_path)
    event = store.record_domain_grader_calibration(rid, report=json.dumps(report).encode(),
                                                 artifacts=artifacts)
    assert event['data']['live_agent_cases_executed'] == 0
    assert store.evidence(rid)['E13']['kind'] == 'bounded_native_domain_grader_calibration'
    assert 'frozen_resource_evaluation' not in store.get(rid)['latest']
    assert store.decide(rid)['activation_permitted'] is False
    assert any('no supported live-agent replay' in reason
               for reason in store.decide(rid)['reasons'])


@pytest.mark.parametrize('fault', ['agent', 'complete', 'skill_lift', 'candidate',
    'missing_control',
    'wrong_answer', 'recomputed_reward', 'contract', 'parser', 'dataset', 'native_bool', 'model',
    'secret_environment', 'unfinished', 'duplicate_case', 'wrong_provenance'])
def test_calibration_rejects_promoted_scope_and_forged_artifacts(tmp_path, fault):
    store, rid, report, artifacts = calibration(tmp_path)
    trials = json.loads(artifacts['native-trials.json'])
    key = next(iter(trials))
    item = trials[key]
    if fault in ('agent', 'complete', 'skill_lift', 'candidate'):
        field = {'agent': 'agent_execution', 'complete': 'complete', 'skill_lift': 'skill_lift',
                 'candidate': 'candidate_sha256'}[fault]
        report[field] = 'unsupported'
    elif fault == 'missing_control':
        del trials[key]
    elif fault in ('wrong_answer', 'recomputed_reward'):
        value = json.loads(item['answer'])
        value['receipt']['total'] = 0.0
        item['answer'] = json.dumps(value)
        if fault == 'recomputed_reward':
            item['reward'] = grade_answer(item['answer'], json.loads(item['contract_json']))
            item['trial']['verifier_result']['rewards']['overall'] = 0.0
    elif fault == 'contract':
        item['contract_json'] = '{}'
    elif fault == 'parser':
        artifacts['parser.py'] = b'changed'
    elif fault == 'dataset':
        report['dataset_sha256'] = 'b' * 64
    elif fault == 'native_bool':
        item['trial']['verifier_result']['rewards']['overall'] = True
    elif fault == 'model':
        item['trial']['config']['agent']['model_name'] = 'live-model'
    elif fault == 'secret_environment':
        item['trial']['config']['environment']['env'] = {'API_KEY': 'fake-only'}
    elif fault == 'unfinished':
        item['trial']['finished_at'] = None
    else:
        prep = json.loads(artifacts['preparation.json'])
        if fault == 'duplicate_case':
            prep['tasks'][1] = prep['tasks'][0]
        else:
            prep['tasks'][0]['provenance'] = 'authored'
        artifacts['preparation.json'] = json.dumps(prep).encode()
    artifacts['native-trials.json'] = json.dumps(trials).encode()
    report['artifacts'] = {k:digest(v) for k, v in artifacts.items()}
    with pytest.raises(ValueError):
        store.record_domain_grader_calibration(rid, report=json.dumps(report).encode(),
                                              artifacts=artifacts)
    assert 'domain_grader_calibration' not in store.get(rid)['latest']
