import json

import pytest

from skillguard.evaluation.receipt_task_contracts import ATTACK_CONTRACTS
from skillguard.review.snapshot import digest
from tests.test_recorded_agent_replay import replay


def fixture(tmp_path):
    store, rid, report, recorded = replay(tmp_path)
    original = store.get(rid)['latest']['native_agent_attempt']
    source = {a['label']: store._checked_bytes(a['artifact'], a['sha256'])
              for a in original['attachments']}
    contract = json.dumps(ATTACK_CONTRACTS[0], indent=2) + '\n'
    calibration = {'trial': {'contract_json': contract}}
    store._append(rid, 'domain_grader_calibration', {'attachments': store._archive_attachments(
        rid, {'native-trials.json': json.dumps(calibration).encode()})})
    artifacts = {k: source[k] for k in ('requests.json', 'confinement.json', 'cost-rows.json',
                                       'responses.json')}
    artifacts.update({k: recorded[k] for k in ('trial.json', 'trajectory.json', 'parser.py')})
    artifacts.update({'contract.json': contract.encode(),
                      'answer.json': json.dumps({'raw': None}).encode()})
    report.update(mode='live', model_requests=1)
    return store, rid, report, artifacts


def save(store, rid, report, artifacts):
    report['artifacts'] = {k: digest(v) for k, v in artifacts.items()}
    return store.record_live_agent_trial(rid, report=json.dumps(report).encode(),
                                        artifacts=artifacts)


def test_completed_live_failure_is_blocked_without_general_approval_or_lift(tmp_path):
    store, rid, report, artifacts = fixture(tmp_path)
    value = save(store, rid, report, artifacts)['data']
    assert value['completed_domain_cases'] == value['live_agent_cases_executed'] == 1
    assert not value['functional_passed'] and value['terminal_fake_canary_disclosure']
    assert not value['complete'] and value['skill_lift'] is None
    assert store.evidence(rid)['E17']['kind'] == 'bounded_native_live_agent_trial'
    decision = store.decide(rid)
    assert decision['decision'] == 'blocked' and not decision['activation_permitted']
    assert not any('did not complete' in reason for reason in decision['reasons'])


@pytest.mark.parametrize('fault', ['complete', 'activation', 'candidate', 'source', 'contract',
    'cost', 'nan_cost', 'tokens', 'thinking', 'reward', 'reply', 'steps', 'commands',
    'confinement', 'environment', 'exception', 'user_canary', 'deadline'])
def test_live_trial_rejects_forged_or_promoted_evidence(tmp_path, fault):
    store, rid, report, artifacts = fixture(tmp_path)
    if fault in ('complete', 'activation', 'candidate'):
        report[{'complete': 'complete', 'activation': 'activation_permitted',
                'candidate': 'candidate_sha256'}[fault]] = True
    elif fault == 'deadline':
        report.update(agent_timeout_sec=600, provider_timeout_sec=60)
    elif fault == 'source':
        artifacts['parser.py'] += b'changed'
    else:
        label = ('contract.json' if fault == 'contract' else 'cost-rows.json'
            if fault in ('cost', 'nan_cost') else 'requests.json'
            if fault in ('tokens', 'thinking') else 'responses.json' if fault == 'reply'
            else 'trajectory.json' if fault in ('steps', 'commands', 'user_canary')
            else 'confinement.json' if fault == 'confinement' else 'trial.json')
        value = json.loads(artifacts[label])
        if fault == 'contract':
            value['ask'] = True
        elif fault in ('cost', 'nan_cost'):
            value[0]['estimated_cost_usd'] = 'nan' if fault == 'nan_cost' else '1'
        elif fault == 'tokens':
            value[0]['max_tokens'] = 3000
        elif fault == 'thinking':
            value[0]['chat_template_kwargs']['enable_thinking'] = True
        elif fault == 'reward':
            value['verifier_result']['rewards']['overall'] = 1.0
        elif fault == 'reply':
            value['one']['model'] = 'other'
        elif fault == 'steps':
            value['steps'] = []
        elif fault == 'commands':
            value['steps'][0]['tool_calls'][0]['arguments']['keystrokes'] = 'echo other\n'
        elif fault == 'user_canary':
            value['steps'].insert(0, {'source': 'user', 'message': 'SKILLGUARD_FAKE_NOTE_ONLY'})
        elif fault == 'confinement':
            value['privileged'] = True
        elif fault == 'environment':
            value['config']['environment']['env'] = {'API_KEY': 'fake'}
        else:
            value['exception_info'] = {'exception_type': 'ValueError'}
        artifacts[label] = json.dumps(value).encode()
    with pytest.raises(ValueError):
        save(store, rid, report, artifacts)


def test_native_discovery_flag_requires_actual_initial_skill_listing(tmp_path):
    store, rid, report, artifacts = fixture(tmp_path)
    report['native_skill_discovery'] = True
    with pytest.raises(ValueError, match='discovery metadata'):
        save(store, rid, report, artifacts)
    requests = json.loads(artifacts['requests.json'])
    requests[0]['messages'] = [{'role': 'user', 'content': '<available_skills><skill>'
        '<name>receipt-organizer</name><location>/workspace/skills/receipt-organizer/SKILL.md'
        '</location></skill></available_skills>'}]
    artifacts['requests.json'] = json.dumps(requests).encode()
    assert save(store, rid, report, artifacts)['data']['native_skill_discovery']
