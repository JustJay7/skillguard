import json
import subprocess

import pytest

from scripts import receipt_live_workflow as live_workflow


@pytest.mark.parametrize('approved', [False, True])
def test_approval_and_consumed_claim_prevent_native_start(tmp_path, monkeypatch, approved):
    results = tmp_path / 'results'
    results.mkdir()
    proposal = results / 'receipt-live-probe-test.json'
    proposal.write_text(json.dumps({'execution_enabled': approved,
        'status': 'authorized_2026_10_10' if approved else 'awaiting_approval',
        'runtime': 'openshell', 'capture_native': True}))
    monkeypatch.setattr(live_workflow, 'prepare_environment',
                        lambda *args: pytest.fail('No native setup allowed'))
    if approved:
        claims = live_workflow.proposal_claim_path(results, proposal)
        claims.parent.mkdir(exist_ok=True)
        claims.write_text('{}')
        with pytest.raises(FileExistsError, match='consumed'):
            live_workflow.workflow(tmp_path, proposal)
    else:
        result = live_workflow.workflow(tmp_path, proposal)
        assert result['status'] == 'awaiting_approval' and result['model_requests'] == 0


@pytest.mark.parametrize('failure', ['preflight', 'live', None])
def test_workflow_finally_stops_native_vm_and_never_retries_paid_trial(
        tmp_path, monkeypatch, failure):
    results = tmp_path / 'results'
    (results / 'integration').mkdir(parents=True)
    proposal = results / 'receipt-live-probe-test.json'
    proposal.write_text(json.dumps({'execution_enabled': True,
        'status': 'authorized_2026_10_22', 'runtime': 'openshell', 'capture_native': True}))
    monkeypatch.setattr(live_workflow, 'prepare_environment', lambda *args: {})
    commands, calls = [], []

    def command(args, **kwargs):
        commands.append(args)
        data = ('{"name":"sgtrace-clean","status":"Stopped"}\n'
                if args[:2] == ['limactl', 'list'] else '')
        return subprocess.CompletedProcess(args, 0, data, '')

    def run(root, *, live, **options):
        calls.append(live)
        assert options == {'proposal_path': proposal, 'runtime': 'openshell',
                           'capture_native': True}
        if live and failure == 'live':
            raise RuntimeError('Fixture transport failure')
        return {'passed': failure != 'preflight', 'run_id': 'fixture', 'model_requests': 0}

    monkeypatch.setattr(live_workflow, 'recorded_command', command)
    monkeypatch.setattr(live_workflow, 'run', run)
    monkeypatch.setattr(live_workflow, 'finalize', lambda *args: {
        'passed': False, 'decision': {'decision': 'blocked'}})
    result = live_workflow.workflow(tmp_path, proposal)
    assert result['runner_stopped'] and not result['activation_permitted']
    assert ['limactl', 'stop', 'sgtrace-clean'] in commands
    assert calls == ([False] if failure == 'preflight' else [False, True])
    assert result['status'] == ('failed' if failure else 'verified')
    if not failure:
        assert not result['functional_passed'] and result['decision']['decision'] == 'blocked'
