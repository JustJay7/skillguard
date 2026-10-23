import json
from pathlib import Path

import pytest

from skillguard.models.bounded_transport import MODEL
from skillguard.review.snapshot import digest
from tests.test_domain_calibration_evidence import calibration


def attempt(tmp_path):
    store, rid, _, _ = calibration(tmp_path)
    candidate = store.get(rid)
    trial = {'finished_at': '2026-10-06T16:00:00Z',
        'exception_info': {'exception_type': 'InternalServerError'}, 'verifier_result': None,
        'config': {'agent': {'name': 'terminus-2', 'model_name': 'openai/' + MODEL, 'env': {},
            'kwargs': {'max_turns': 4, 'enable_summarize': False,
                'api_base': 'https://api.tokenfactory.nebius.com/v1',
                'llm_kwargs': {'max_tokens': 2000, 'num_retries': 0,
                    'extra_body': {'chat_template_kwargs': {'enable_thinking': False}}}}},
            'environment': {'type': 'docker', 'env': {}, 'mounts': None}}}
    request = {'model': MODEL, 'max_tokens': 2000,
               'chat_template_kwargs': {'enable_thinking': False}}
    row = {'call_id': 'one', 'model': MODEL, 'status': 'completed', 'reserved_cost_usd': '',
           'estimated_cost_usd': '0.0000054', 'input_tokens': '10', 'output_tokens': '20'}
    proof = {'passed': True, 'uid': 1000, 'fake_key_matches': [], 'network_mode': 'none',
        'pid_mode': '', 'privileged': False, 'cap_add': None, 'mounts_safe': True,
        'controller_root_visible': False, 'docker_socket_visible': False,
        'credential_in_container_config': False}
    artifacts = {k: json.dumps(v).encode() for k, v in {
        'trial.json': trial, 'trajectory.json': {'steps': [{'source': 'user'}]},
        'requests.json': [request], 'cost-rows.json': [row], 'confinement.json': proof,
        'responses.json': {'one': {'usage': {'prompt_tokens': 10, 'completion_tokens': 20}}}
    }.items()}
    artifacts['parser.py'] = (Path(candidate['snapshot']) / 'scripts/parse_receipt.py').read_bytes()
    report = {'candidate_sha256': candidate['candidate_sha256'], 'mode': 'live',
        'complete': False, 'passed': False, 'activation_permitted': False,
        'skill_lift': None, 'completed_domain_cases': 0, 'model_requests': 1}
    return store, rid, report, artifacts


def record(store, rid, report, artifacts):
    report['artifacts'] = {k: digest(v) for k, v in artifacts.items()}
    return store.record_native_agent_attempt(rid, report=json.dumps(report).encode(),
                                             artifacts=artifacts)


def test_incomplete_attempt_is_evidence_and_cannot_activate(tmp_path):
    store, rid, report, artifacts = attempt(tmp_path)
    event = record(store, rid, report, artifacts)
    assert event['data']['completed_domain_cases'] == 0
    assert store.evidence(rid)['E14']['kind'] == 'bounded_incomplete_native_agent_attempt'
    decision = store.decide(rid)
    assert decision['activation_permitted'] is False
    assert any('did not complete' in r for r in decision['reasons'])


@pytest.mark.parametrize('fault', ['complete', 'pass', 'activation', 'candidate', 'source',
    'tokens', 'thinking', 'model', 'cost', 'request_count', 'confinement', 'trial_success',
    'environment', 'sdk_options'])
def test_incomplete_attempt_cannot_be_promoted_or_forged(tmp_path, fault):
    store, rid, report, artifacts = attempt(tmp_path)
    if fault in ('complete', 'pass', 'activation', 'candidate'):
        report[{'complete': 'complete', 'pass': 'passed', 'activation': 'activation_permitted',
                'candidate': 'candidate_sha256'}[fault]] = True
    elif fault == 'source':
        artifacts['parser.py'] += b'changed'
    else:
        label = ('requests.json' if fault in ('tokens', 'thinking', 'model', 'request_count')
            else 'cost-rows.json' if fault == 'cost' else 'confinement.json'
            if fault == 'confinement' else 'trial.json')
        value = json.loads(artifacts[label])
        if fault == 'tokens':
            value[0]['max_tokens'] = 4000
        elif fault == 'thinking':
            value[0]['chat_template_kwargs']['enable_thinking'] = True
        elif fault == 'model':
            value[0]['model'] = 'different'
        elif fault == 'request_count':
            value *= 5
        elif fault == 'cost':
            value[0]['estimated_cost_usd'] = '0'
        elif fault == 'confinement':
            value['controller_root_visible'] = True
        elif fault == 'trial_success':
            value['exception_info'] = None
        elif fault == 'environment':
            value['config']['environment']['env'] = {'NEBIUS_API_KEY': 'fake'}
        elif fault == 'sdk_options':
            value['config']['agent']['kwargs']['llm_kwargs']['api_key'] = 'fake'
        artifacts[label] = json.dumps(value).encode()
    with pytest.raises(ValueError):
        record(store, rid, report, artifacts)
