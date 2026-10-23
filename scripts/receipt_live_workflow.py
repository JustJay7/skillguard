"""Compose one authorized native live trial with exact preflight and VM cleanup."""
from __future__ import annotations

import argparse
import fcntl
import json
import uuid
from pathlib import Path

from scripts.finalize_live_agent_trial import finalize
from scripts.linux_runner import prepare_environment
from scripts.receipt_workflow import recorded_command
from scripts.run_native_evaluation import PREFIX
from scripts.run_receipt_agent_probe import run
from skillguard.models.probe_claim import proposal_claim_path


def workflow(root: Path, proposal: Path) -> dict:
    path = root.parent / 'work/lr/core-operation.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _workflow(root, proposal)


def _workflow(root: Path, proposal: Path) -> dict:
    proposal = proposal.resolve()
    if not proposal.is_relative_to(root / 'results'):
        raise ValueError('Operator-owned local proposal required')
    value = json.loads(proposal.read_text())
    if (value.get('execution_enabled') is not True or value.get('status') not in {
            'authorized_2026_10_06', 'authorized_2026_10_08', 'authorized_2026_10_10',
            'authorized_2026_10_22'}):
        return {'status': 'awaiting_approval', 'model_requests': 0, 'activation_permitted': False}
    if value.get('runtime') != 'openshell' or value.get('capture_native') is not True:
        raise ValueError('Scoped OpenShell capture proposal required')
    if proposal_claim_path(root / 'results', proposal).exists():
        raise FileExistsError('The approved probe was already consumed')
    folder = root / 'results/integration' / ('receipt-live-workflow-' + uuid.uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    env = prepare_environment(root, 'lima')
    report = {'run_id': folder.name, 'status': 'failed', 'model_requests': 0,
        'activation_permitted': False, 'complete': False,
        'scope': 'One authorized native trial; no full resistance or Skill Lift claim'}

    def command(args, name, timeout=90):
        return recorded_command(args, root=root, env=env, output=folder / name, timeout=timeout)

    try:
        if command(['limactl', 'start', '--yes', '--timeout', '90s', 'sgtrace-clean'],
                   'vm-start.txt', 120).returncode:
            raise RuntimeError('Native runner did not start')
        if (command(PREFIX + ['systemctl', 'is-active', 'skillguard-openshell'],
                    'gateway-state.txt').returncode
                and command(PREFIX + ['systemd-run', '--unit=skillguard-openshell', '--uid=root',
                    '--property=SetLoginEnvironment=yes', '--property=UMask=0077',
                    '--setenv=OPENSHELL_LOCAL_TLS_DIR=/root/.local/state/openshell/tls',
                    '/usr/bin/openshell-gateway'], 'gateway-start.txt').returncode):
            raise RuntimeError('Native gateway did not start')
        options = {'proposal_path': proposal, 'runtime': 'openshell', 'capture_native': True}
        preflight = run(root, live=False, **options)
        report['preflight'] = preflight['run_id']
        if not preflight.get('passed'):
            raise ValueError('Exact native preflight failed; no live request attempted')
        report['model_requests'] = None
        live = run(root, live=True, **options)
        report.update(live_run=live['run_id'], model_requests=live['model_requests'])
        if live.get('error'):
            raise ValueError('Live trial failed; retain native report and reservation')
        verified = finalize(root, root / 'results/integration' / live['run_id'])
        report.update(status='verified', functional_passed=verified['passed'],
                      decision=verified['decision'], agent_completion_confirmed=verified.get(
                          'live_trial_evidence', {}).get('agent_completion_confirmed', False))
    except Exception as error:
        report['error_type'] = type(error).__name__
    finally:
        if command(['limactl', 'stop', 'sgtrace-clean'], 'vm-stop.txt').returncode:
            command(['limactl', 'stop', '--force', 'sgtrace-clean'], 'vm-force-stop.txt')
        state = command(['limactl', 'list', '--json'], 'vm-states.txt')
        report['runner_states'] = ({v['name']: v['status'] for v in map(
            json.loads, state.stdout.splitlines())} if state.returncode == 0 else {})
        report['runner_stopped'] = report['runner_states'].get('sgtrace-clean') == 'Stopped'
        raw = json.dumps(report, indent=2) + '\n'
        (folder / 'workflow.json').write_text(raw)
        (root / 'results/receipt-live-workflow-latest.json').write_text(raw)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--proposal', type=Path, required=True)
    args = parser.parse_args()
    result = workflow(Path(__file__).resolve().parents[1], args.proposal)
    print(json.dumps(result, indent=2))
    if result['status'] != 'verified' or not result.get('runner_stopped'):
        raise SystemExit(2)
