import json

import pytest

from skillguard.models.bounded_transport import APP_COMPLETION_PROFILE
from skillguard.review.snapshot import digest
from skillguard.security_review import verify_runner_start_recovery


@pytest.mark.parametrize('fault', [None, 'paid', 'mock_request', 'container',
                                  'exception', 'hash', 'requests'])
def test_start_timeout_recovery_requires_exact_no_agent_failure(tmp_path, fault):
    root = tmp_path / 'results/integration'
    folder, preflight = root / 'workflow', root / 'keyless'
    folder.mkdir(parents=True)
    native = preflight / 'native-job'
    (native / 'jobs/receipt-probe/task').mkdir(parents=True)
    (native / 'capture').mkdir()
    workflow = {'status': 'failed', 'model_requests': 0, 'runner_stopped': True,
                'error_type': 'ValueError', 'preflight': 'keyless'}
    report = {'mode': 'offline', 'maximum_model_requests': 8, 'model_requests': 0,
              'app_execution_profile': APP_COMPLETION_PROFILE}
    controller = {'mode': 'offline', 'model_requests': 1 if fault == 'paid' else 0,
                  'mock_http_requests': 1 if fault == 'mock_request' else 0,
                  'confinement_passed': False}
    trial = {'exception_info': {'exception_type': 'other' if fault == 'exception' else
                'EnvironmentStartTimeoutError', 'exception_traceback':
                "harbor_openshell_environment.py 'docker', 'build' TimeoutError"}}
    artifacts = {'workflow': (folder / 'workflow.json', workflow),
        'preflight': (preflight / 'report.json', report),
        'controller_result': (native / 'controller-result.json', controller),
        'trial_result': (native / 'jobs/receipt-probe/task/result.json', trial)}
    recovery = {'reason': 'keyless_environment_start_timeout'}
    for name, (path, value) in artifacts.items():
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        recovery[name + '_sha256'] = digest(raw)
    (native / 'capture/capture.json').write_text(json.dumps({
        'container_full_id': 'started' if fault == 'container' else None}))
    if fault == 'requests':
        (native / 'requests.json').write_text('[]')
    if fault == 'hash':
        recovery['trial_result_sha256'] = 'changed'
    (folder / 'vm-start.txt').write_bytes(b'original VM startup')
    recovery['vm_start_sha256'] = digest((folder / 'vm-start.txt').read_bytes())
    previous = {'verified_probes': 0, 'probes': [], 'incomplete_probe': {
        'workflow_run': 'workflow', 'model_requests': 0, 'native_run': None}}
    if fault:
        with pytest.raises(ValueError, match='keyless environment-start'):
            verify_runner_start_recovery(tmp_path, previous, recovery)
    else:
        verify_runner_start_recovery(tmp_path, previous, recovery)
