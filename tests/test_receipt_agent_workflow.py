import json
import subprocess

import pytest

from scripts import receipt_agent_workflow
from skillguard.review.snapshot import digest
from tests.test_recorded_agent_replay import replay, save


def setup(tmp_path, monkeypatch, fail_runtime=None):
    store, rid, report, artifacts = replay(tmp_path)
    save(store, rid, report, artifacts)
    root = tmp_path / 'project'
    results = root / 'results'
    preparation = results / 'integration/local-parser-8fc64684/preparation.json'
    preparation.parent.mkdir(parents=True)
    (results / 'integration/source-live').mkdir()
    preparation.write_text(json.dumps({'run_id': 'local-parser-8fc64684',
        'store': str(store.root), 'review_id': rid, 'native_pending_id': 'fixture-pending'}))
    (results / 'receipt-agent-live-latest.json').write_text(json.dumps({
        'mode': 'live', 'run_id': 'source-live', 'parser_sha256': digest(artifacts['parser.py'])}))
    calls = []

    def native(args, **kwargs):
        calls.append(args)
        data = ('{"name":"sgtrace-clean","status":"Stopped"}\n'
                if args[:2] == ['limactl', 'list'] else '')
        return subprocess.CompletedProcess(args, 0, data, '')

    def run(path, *, live, runtime, recorded_from=None, capture_native=False):
        assert path == root and live is False
        if recorded_from:
            assert recorded_from == results / 'integration/source-live' and capture_native
        if runtime == fail_runtime and recorded_from:
            raise ValueError('Offline fixture capture failure')
        return {'run_id': runtime + '-fixture', 'passed': True,
                'native_agent_steps': 4, 'model_requests': 0}

    def finalized(path, folder):
        return {'run_id': folder.name, 'native_agent_steps': 4, 'model_requests': 0}

    monkeypatch.setattr(receipt_agent_workflow.subprocess, 'run', native)
    monkeypatch.setattr(receipt_agent_workflow, 'run', run)
    monkeypatch.setattr(receipt_agent_workflow, 'finalize_capture', finalized)
    monkeypatch.setattr(receipt_agent_workflow, 'finalize_enforced', finalized)
    return root, calls


def test_native_workflow_delegates_offline_and_persists_cleanup(tmp_path, monkeypatch):
    root, calls = setup(tmp_path, monkeypatch)
    result = receipt_agent_workflow.workflow(root)
    assert result['diagnostic_passed'] and result['model_requests'] == 0
    assert result['runner_stopped'] and result['active_skill_absent']
    assert not result['activation_permitted'] and result['decision']['decision'] == 'blocked'
    assert len(result['runs']) == 2
    assert ['limactl', 'stop', 'sgtrace-clean'] in calls
    assert json.loads((root / 'results/receipt-agent-workflow-latest.json').read_text()) == result


@pytest.mark.parametrize('runtime', ['docker', 'openshell'])
def test_native_failed_replay_still_stops_vm_and_preserves_blocked_review(
        tmp_path, monkeypatch, runtime):
    root, calls = setup(tmp_path, monkeypatch, fail_runtime=runtime)
    result = receipt_agent_workflow.workflow(root)
    assert not result['diagnostic_passed'] and 'capture failure' in result['error']
    assert ['limactl', 'stop', 'sgtrace-clean'] in calls
    assert result['runner_stopped'] and result['archive_preserved']
    assert not result['activation_permitted']
