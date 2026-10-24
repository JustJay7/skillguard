import json
from pathlib import Path

import pytest

from scripts.run_receipt_agent_probe import prepared_task
from skillguard.core import CoreWorkspace
from skillguard.core_agent import (
    agent_checks_valid,
    parser_checks_valid,
    prepare_proposal,
    review_test_digest,
    selected_candidate,
)
from skillguard.evaluation.agent_task_protocol import PROTOCOL
from skillguard.review.snapshot import artifact_tree_digest
from tests.test_core import candidate, passing_test, revision


@pytest.fixture
def selected(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    w = CoreWorkspace(root, root / 'results/core')
    rid = candidate(w)
    passing_test(w, rid)
    task = root / 'results/source'
    (task / 'environment/skills/receipt-organizer').mkdir(parents=True)
    (task / 'environment/skills/receipt-organizer/SKILL.md').write_text('wrong source')
    (task / 'environment/Dockerfile').write_text('FROM python:3.12-slim\nUSER 1000:1000\n')
    (task / 'task.toml').write_text('[environment]\nskills_dir="/workspace/skills"\n')
    (task / 'solution').mkdir()
    (task / 'solution/reference.json').write_text('{}')
    template = {'maximum_model_requests': 6, 'task': {
        'task': str(task), 'task_sha256': artifact_tree_digest(task),
                         'case_id': 'receipt-organizer-001'}, 'native_skill_discovery': True}
    (root / 'results/receipt-live-probe-agent-record-complete-2026-10-22.json').write_text(
        json.dumps(template))
    (root / 'results/receipt-agent-tasks-latest.json').write_text('{}')
    return w, rid


def test_selected_review_is_copied_into_native_task_instead_of_legacy_skill(selected):
    w, rid = selected
    review = w.store.get(rid)
    first = prepare_proposal(w.root, w.store.root, review)
    second = prepare_proposal(w.root, w.store.root, review)
    assert first != second
    from skillguard.models.probe_claim import proposal_claim_path

    assert json.loads(first.read_text())['app_request_id'] != json.loads(
        second.read_text())['app_request_id']
    assert proposal_claim_path(w.root / 'results', first) != proposal_claim_path(
        w.root / 'results', second)
    assert parser_checks_valid(review) and not agent_checks_valid(review)
    folder = w.root / 'results/attempt'
    folder.mkdir()
    task, _, info = prepared_task(w.root, folder, first)
    assert info['candidate_sha256'] == review['candidate_sha256']
    for name in ('SKILL.md', 'scripts/parse_receipt.py'):
        assert (task / 'environment/skills/receipt-organizer' / name).read_bytes() == (
            Path(review['snapshot']) / name).read_bytes()
    assert not (task / 'solution').exists()
    assert 'needs_clarification' in (task / 'instruction.md').read_text()
    assert 'choosing your own extraction tools' in (task / 'instruction.md').read_text()
    assert 'Use the existing parser' not in (task / 'instruction.md').read_text()


def test_parser_success_alone_cannot_approve_an_agent_skill(selected, monkeypatch):
    w, rid = selected
    monkeypatch.setattr(w, 'native',
                        lambda *a, **kw: pytest.fail('Do not activate parser-only skill'))
    with pytest.raises(ValueError, match='agent/receipt'):
        w.approve(rid, revision=revision(w, rid), acknowledge_limits=True)
    review = w.store.get(rid)
    w.store._append(rid, 'core_agent_test', {
        'agent_task_passed': True, 'candidate_sha256': review['candidate_sha256'],
        'core_test_sha256': review_test_digest(review), 'instruction_protocol': PROTOCOL})
    assert agent_checks_valid(w.store.get(rid))
    proposal = prepare_proposal(w.root, w.store.root, review)
    old_target = json.loads(proposal.read_text())['review_target']
    w.store._append(rid, 'core_test', {**review['latest']['core_test'], 'run_id': 'new-check'})
    assert not agent_checks_valid(w.store.get(rid))
    with pytest.raises(ValueError, match='current passing'):
        selected_candidate(w.root, old_target)


def test_installed_proposal_rechecks_active_version_before_any_model_call(selected):
    w, rid = selected
    proposal = prepare_proposal(w.root, w.store.root, w.store.get(rid))
    target = json.loads(proposal.read_text())['review_target']
    with pytest.raises(ValueError, match='version changed'):
        selected_candidate(w.root, {**target, 'installed_version': 'no-longer-active'})


def test_later_success_cannot_erase_prior_prohibited_agent_disclosure(selected):
    w, rid = selected
    review = w.store.get(rid)
    passing = {'agent_task_passed': True, 'candidate_sha256': review['candidate_sha256'],
               'core_test_sha256': review_test_digest(review), 'instruction_protocol': PROTOCOL}
    w.store._append(rid, 'core_agent_test', {**passing, 'agent_task_passed': False,
                                          'terminal_fake_canary_disclosure': True})
    w.store._append(rid, 'core_agent_test', passing)
    assert not agent_checks_valid(w.store.get(rid))
    with pytest.raises(ValueError, match='Earlier prohibited disclosure'):
        prepare_proposal(w.root, w.store.root, w.store.get(rid))


def test_new_app_probe_can_fit_cap_without_releasing_historical_unknown(selected):
    import csv

    from skillguard.models.probe_claim import claim_probe
    from tests.test_probe_claim import ledger

    w, rid = selected
    proposal = json.loads(prepare_proposal(w.root, w.store.root, w.store.get(rid)).read_text())
    path = w.root / 'results/cost.csv'
    ledger(path, [{'call_id': 'unknown', 'reserved_cost_usd': '.25'},
                  {'call_id': 'earlier', 'estimated_cost_usd': '.12544566'}])
    claim_probe(path, w.root / 'results/new.claim.json', {**proposal, 'run_id': 'app'})
    rows = list(csv.DictReader(path.open()))
    assert rows[0]['reserved_cost_usd'] == '.25'
    assert sum(float(r['reserved_cost_usd'] or r['estimated_cost_usd'] or 0)
               for r in rows) == pytest.approx(.45544566)
    assert rows[-1]['reserved_cost_usd'] == '0.08'


def test_installed_agent_run_is_fresh_bound_to_active_source_and_rejects_stale_version(
        selected, monkeypatch):
    import skillguard.core_agent as module
    from tests.test_security_review import passing_security

    w, rid = selected
    review = w.store.get(rid)
    w.store._append(rid, 'core_agent_test', {
        'agent_task_passed': True, 'candidate_sha256': review['candidate_sha256'],
        'core_test_sha256': review_test_digest(review), 'instruction_protocol': PROTOCOL})
    passing_security(w, rid)
    manifest = {'id': 'version', 'review_id': rid,
                'candidate_sha256': review['candidate_sha256']}
    monkeypatch.setattr(w, 'installed', lambda: {'active': 'version'})
    monkeypatch.setattr(w, 'version', lambda vid: (manifest, Path(review['snapshot'])))
    calls = []

    def execute(root, store, reviewed, *, fresh, installed_version):
        calls.append((reviewed['candidate_sha256'], fresh, installed_version))
        return {'agent_task_passed': True, 'answer': {'receipt': {'total': 23}},
                'model_requests': 5, 'run_id': 'fresh-native-run', 'skill_use': {}}

    monkeypatch.setattr(module, 'run_test', execute)
    with pytest.raises(ValueError, match='changed'):
        w.run_installed_agent(expected_active='stale')
    assert calls == []
    result = w.run_installed_agent(expected_active='version')
    assert calls == [(review['candidate_sha256'], True, 'version')]
    assert result['version'] == 'version' and result['model_requests'] == 5
    assert result['agent_completion_confirmed'] and result['run_id'] == 'fresh-native-run'


@pytest.mark.parametrize('fault', [None, 'capture', 'runtime', 'source'])
def test_portable_app_requires_current_native_review_and_captured_preflight(selected, fault):
    from scripts.run_receipt_agent_probe import verify_enforced_prerequisites

    w, rid = selected
    proposal = json.loads(prepare_proposal(w.root, w.store.root, w.store.get(rid)).read_text())
    preflight = {'runtime': 'openshell', 'capture_native': True}
    if fault == 'capture':
        preflight['capture_native'] = False
    elif fault == 'runtime':
        preflight['runtime'] = 'docker'
    elif fault == 'source':
        proposal['review_target']['candidate_sha256'] = 'changed'
    if fault:
        with pytest.raises(ValueError):
            verify_enforced_prerequisites(w.root, proposal, preflight)
    else:
        # No historical development report exists on this new host.
        verify_enforced_prerequisites(w.root, proposal, preflight)
    (w.root / 'results/receipt-agent-workflow-latest.json').write_text(
        json.dumps({'diagnostic_passed': False}))
    with pytest.raises(ValueError, match='recorded enforcement'):
        verify_enforced_prerequisites(w.root, {}, {'runtime': 'openshell', 'capture_native': True})


def test_new_app_bound_does_not_modify_old_template_or_historical_trial(selected):
    from skillguard.models.bounded_transport import APP_COMPLETION_PROFILE

    w, rid = selected
    template = w.root / 'results/receipt-live-probe-agent-record-complete-2026-10-22.json'
    original = template.read_bytes()
    proposal = json.loads(prepare_proposal(w.root, w.store.root, w.store.get(rid)).read_text())
    assert proposal['maximum_model_requests'] == 8
    assert proposal['app_execution_profile'] == APP_COMPLETION_PROFILE
    assert template.read_bytes() == original
    assert json.loads(original)['maximum_model_requests'] == 6
