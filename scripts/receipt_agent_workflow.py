from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from scripts.finalize_agent_capture import finalize as finalize_capture
from scripts.finalize_enforced_agent_replay import finalize as finalize_enforced
from scripts.linux_runner import prepare_environment
from scripts.run_native_evaluation import PREFIX
from scripts.run_receipt_agent_probe import run
from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore


def workflow(root: Path) -> dict:
    source = json.loads((root / 'results/receipt-agent-live-latest.json').read_text())
    original = root / 'results/integration' / source['run_id']
    if source.get('mode') != 'live' or not original.is_dir():
        raise ValueError('A retained real live attempt is required; no inference is initiated here')
    parent_path = root / 'results/integration/local-parser-8fc64684/preparation.json'
    parent = json.loads(parent_path.read_text())
    folder = root / 'results/integration' / ('receipt-agent-workflow-' + uuid.uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    env = prepare_environment(root, 'lima')
    report = {'run_id': folder.name, 'model_requests': 0, 'complete': False,
              'activation_permitted': False, 'runs': [],
              'scope': 'Native scripted preflight and unchanged recorded reply comparison; '
                       'not fresh inference, Skill Lift or general protection'}

    def native(args, name, timeout=90, check=True):
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout)
        (folder / name).write_text(result.stdout + result.stderr)
        if check and result.returncode:
            raise RuntimeError('Native lifecycle command failed: ' + name)
        return result

    try:
        native(['limactl', 'start', '--yes', '--timeout', '90s', 'sgtrace-clean'],
               'vm-start.txt', timeout=120)
        active = native(PREFIX + ['systemctl', 'is-active', 'skillguard-openshell'],
                        'gateway-state.txt', check=False)
        if active.returncode:
            native(PREFIX + ['systemd-run', '--unit=skillguard-openshell', '--uid=root',
                '--property=SetLoginEnvironment=yes', '--property=UMask=0077',
                '--setenv=OPENSHELL_LOCAL_TLS_DIR=/root/.local/state/openshell/tls',
                '/usr/bin/openshell-gateway'], 'gateway-start.txt')
        preflight = run(root, live=False, runtime='openshell')
        report['preflight'] = preflight['run_id']
        if not preflight['passed']:
            raise ValueError('Native OpenShell fake-key scripted preflight failed')
        for runtime, finalizer in (('docker', finalize_capture), ('openshell', finalize_enforced)):
            result = run(root, live=False, recorded_from=original,
                         capture_native=True, runtime=runtime)
            if result.get('error'):
                raise ValueError('Recorded native run failed: ' + result['run_id'])
            finalized = finalizer(root, root / 'results/integration' / result['run_id'])
            report['runs'].append({'runtime': runtime, 'run_id': finalized['run_id'],
                'native_agent_steps': finalized['native_agent_steps'],
                'model_requests': finalized['model_requests']})
        report['diagnostic_passed'] = True
    except Exception as error:
        report['diagnostic_passed'] = False
        report['error'] = str(error)
    finally:
        stopped = native(['limactl', 'stop', 'sgtrace-clean'], 'vm-stop.txt', check=False)
        if stopped.returncode:
            native(['limactl', 'stop', '--force', 'sgtrace-clean'],
                   'vm-force-stop.txt', check=False)
        state = native(['limactl', 'list', '--json'], 'vm-states.txt')
        report['runner_states'] = {v['name']: v['status']
            for v in map(json.loads, state.stdout.splitlines())}
        report['runner_stopped'] = report['runner_states'].get('sgtrace-clean') == 'Stopped'
        store = ReviewStore(Path(parent['store']))
        review = store.get(parent['review_id'])
        report['decision'] = store.decide(parent['review_id'])
        profile = folder.parent / parent['run_id'] / 'staging-profile'
        pending = profile / 'pending/skills' / (parent['native_pending_id'] + '.json')
        report['pending_removed'] = not pending.exists() and review['latest'].get(
            'rejection', {}).get('pending_removed', False)
        report['archive_preserved'] = (Path(review['snapshot']).is_dir()
            and digest((Path(review['snapshot']) / 'scripts/parse_receipt.py').read_bytes())
            == source['parser_sha256'])
        report['active_skill_absent'] = not (profile / 'skills/receipt-organizer').exists()
        raw = json.dumps(report, indent=2) + '\n'
        (folder / 'workflow.json').write_text(raw)
        (root / 'results/receipt-agent-workflow-latest.json').write_text(raw)
    return report


if __name__ == '__main__':
    result = workflow(Path(__file__).resolve().parents[1])
    print(json.dumps(result, indent=2))
    if not result['diagnostic_passed'] or not result['runner_stopped']:
        raise SystemExit(2)
