import json

import pytest

from skillguard.evaluation.enforced_live_trial import verify_enforced_live_trial
from skillguard.review.snapshot import digest
from tests.test_enforced_agent_replay import fixture as enforced
from tests.test_live_agent_trial import fixture as live


def fixture(tmp_path):
    (tmp_path / 'live').mkdir()
    (tmp_path / 'native').mkdir()
    store, rid, report, artifacts = live(tmp_path / 'live')
    _, _, _, native = enforced(tmp_path / 'native')
    artifacts.update({k: v for k, v in native.items() if k not in {
        'trial.json', 'parser.py', 'requests.json', 'cost-rows.json', 'responses.json',
        'answer.json', 'contract.json'}})
    trial = json.loads(artifacts['trial.json'])
    trial['config']['environment'] = json.loads(native['trial.json'])['config']['environment']
    artifacts['trial.json'] = json.dumps(trial).encode()
    proof = json.loads(artifacts['confinement.json'])
    proof.update(network_mode='none', pid_mode='', privileged=False, cap_add=None,
                 mounts_safe=False)
    artifacts['confinement.json'] = json.dumps(proof).encode()
    report.update(runtime='openshell', capture_native=True,
                  artifacts={k: digest(v) for k, v in artifacts.items()})
    return store, rid, report, artifacts


def test_fresh_enforced_trial_has_live_credit_but_no_general_resistance_credit(tmp_path):
    _, _, report, artifacts = fixture(tmp_path)
    value = verify_enforced_live_trial(report, artifacts, artifacts['parser.py'])
    assert value['model_requests'] == value['live_agent_cases_executed'] == 1
    assert not value['functional_passed'] and not value['terminal_fake_canary_disclosure']
    assert value['native_sandbox_stopped'] and not value['activation_permitted']
    assert value['capture']['reported_denied_private_opens']


@pytest.mark.parametrize('fault', ['key', 'image', 'capture', 'domain', 'profile'])
def test_fresh_enforced_trial_refuses_changed_proof(tmp_path, fault):
    _, _, report, artifacts = fixture(tmp_path)
    label, field, value = {
        'key': ('confinement.json', 'fake_key_matches', ['fixture-key-visible']),
        'image': ('binding.json', 'image_id', 'wrong'),
        'capture': ('capture.json', 'collector_active_after_job', False),
        'domain': ('trial.json', 'verifier_result', {'rewards': {'overall': 1}}),
        'profile': ('environment-files.json', 'Dockerfile', 'different'),
    }[fault]
    item = json.loads(artifacts[label])
    item[field] = value
    artifacts[label] = json.dumps(item).encode()
    report['artifacts'] = {k: digest(v) for k, v in artifacts.items()}
    with pytest.raises(ValueError):
        verify_enforced_live_trial(report, artifacts, artifacts['parser.py'])
