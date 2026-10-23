import json
import subprocess

import pytest

from scripts import receipt_learning_workflow as workflow
from skillguard.models.probe_claim import proposal_claim_path
from skillguard.review.snapshot import digest


@pytest.mark.parametrize('claim_consumed', [False, True])
def test_resume_preserves_paid_failure_and_retries_only_unconsumed_preflight(
        tmp_path, monkeypatch, claim_consumed):
    folder = tmp_path / 'results/integration/experiment'
    folder.mkdir(parents=True)
    for name in ('scripts/run_receipt_agent_probe.py', 'scripts/native_receipt_controller.py',
                 'skillguard/evaluation/receipt_learning.py',
                 'skillguard/evaluation/receipt_learning_cases_v2.py',
                 'skillguard/evaluation/receipt_repair.py',
                 'skillguard/evaluation/receipt_repair_cases.py',
                 'skillguard/evaluation/receipt_command_audit.py',
                 'skillguard/evaluation/receipt_selected_cases.py',
                 'skillguard/evaluation/receipt_refresh_cases.py',
                 'skillguard/evaluation/selected_skill_evidence.py',
                 'skillguard/evaluation/native_wire.py',
                 'scripts/verify_receipt_learning.py',
                 'skillguard/evaluation/live_agent_trial.py',
                 'skillguard/models/harbor_transport.py',
                 'skillguard/models/bounded_transport.py', 'scripts/native_agent_capture.py',
                 'skillguard/models/probe_claim.py', 'skillguard/core_agent.py',
                 'scripts/harbor_openshell_environment.py',
                 'skillguard/evaluation/receipt_answer_grader.py',
                 'scripts/receipt_learning_workflow.py'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Offline fixture only')
    manifest = {'run_id': 'fixture', 'trials': [
        {'id': 'paid', 'case_id': 'case', 'arm': 'with'},
        {'id': 'offline', 'case_id': 'case', 'arm': 'without'}]}
    path = folder / 'manifest.json'
    path.write_text(json.dumps(manifest))
    first = {'trial_id': 'paid', 'verified': False, 'stage': 'live', 'model_requests': 3,
             'case_id': 'case', 'arm': 'with'}
    state = {'status': 'incomplete', 'manifest_sha256': digest(path.read_bytes()),
             'runtime_identity': {}, 'results': [first,
                 {'trial_id': 'offline', 'stage': 'preflight', 'verified': False}]}
    (folder / 'experiment.json').write_text(json.dumps(state))
    (folder / 'offline-proposal.json').write_text('{}')
    (tmp_path.parent / 'work/lr').mkdir(parents=True, exist_ok=True)
    if claim_consumed:
        claim = proposal_claim_path(tmp_path / 'results', folder / 'offline-proposal.json')
        claim.parent.mkdir(exist_ok=True)
        claim.write_text('{}')
    monkeypatch.setattr(workflow, 'prepare_environment', lambda *args: {})
    calls = []

    def command(args, **kwargs):
        return subprocess.CompletedProcess(args, 0,
            '{"name":"sgtrace-clean","status":"Stopped"}\n'
            if args[:2] == ['limactl', 'list'] else '', '')

    def run(root, *, live, **options):
        calls.append((options['proposal_path'].name, live))
        return {'passed': True, 'run_id': 'fixture', 'model_requests': 2}

    monkeypatch.setattr(workflow, 'recorded_command', command)
    monkeypatch.setattr(workflow, 'run', run)
    monkeypatch.setattr(workflow, 'verify', lambda *args: {
        'trial_id': 'offline', 'case_id': 'case', 'arm': 'without', 'verified': True})
    monkeypatch.setattr(workflow, 'summarize', lambda *args: {'complete_matrix': False})
    if claim_consumed:
        with pytest.raises(ValueError, match='consumed claim'):
            workflow.workflow(tmp_path, path, resume=True)
        assert not calls
    else:
        result = workflow.workflow(tmp_path, path, resume=True)
        assert calls == [('offline-proposal.json', False), ('offline-proposal.json', True)]
        assert result['results'][0] == first
        assert result['infrastructure_failures'][0]['trial_id'] == 'offline'
        assert list(folder.glob('experiment-before-resume-*.json'))
