"""Run the frozen paired matrix via existing native Harbor/SkillEvaluator adapters."""
from __future__ import annotations

import argparse
import fcntl
import json
import shutil
from pathlib import Path

from scripts.linux_runner import prepare_environment
from scripts.receipt_workflow import recorded_command
from scripts.run_native_evaluation import PREFIX
from scripts.run_receipt_agent_probe import run
from scripts.verify_receipt_learning import verify
from skillguard.review.snapshot import digest


def summarize(root: Path, manifest: dict, results: list[dict], folder: Path) -> dict:
    from skillevaluator.tier3.harbor import collector
    from skillevaluator.tier3.harbor.metrics import average_custom_metrics

    pairs = []
    for case in manifest['cases']:
        arms = {r['arm']: r for r in results if r['case_id'] == case['id']}
        if set(arms) == {'with', 'without'}:
            pairs.append({'case_id': case['id'], 'group': case['group'],
                'with': arms['with'].get('task_passed', False),
                'without': arms['without'].get('task_passed', False),
                'verified': all(r.get('verified') for r in arms.values())})
    native_jobs = folder / 'collected-jobs'
    native_jobs.mkdir(exist_ok=True)
    for r in results:
        if not r.get('verified'):
            continue
        source = Path(r['native_trial']).parent
        job = native_jobs / ('receipt-organizer-terminus-2-' + r['arm'])
        destination = job / (r['case_id'] + '__' + source.name)
        if not destination.exists():
            shutil.copytree(source, destination)
    measured_arms = ('with',) if manifest.get('development_only') else ('with', 'without')
    rewards = {arm: collector._extract_rewards(
        native_jobs / ('receipt-organizer-terminus-2-' + arm)) for arm in measured_arms}
    scores = {arm: average_custom_metrics(rows) for arm, rows in rewards.items()}
    native = {'custom_lift': None if manifest.get('development_only') else
        collector._compute_custom_lift(scores['with'], scores['without'],
        rewards['with'], rewards['without'], include_overall=True),
        'conditions': {arm: collector._condition_execution_summary(rows,
            expected_case_ids=[c['native_case_id'] for c in manifest['cases']],
            expected_cases=len(manifest['cases']), n_attempts=1, job_failure='')
            for arm, rows in rewards.items()},
        'scope': 'Unmodified native SkillEvaluator collector primitives over separate bounded jobs'}
    (folder / 'native-collector.json').write_text(json.dumps(native, indent=2) + '\n')
    if manifest.get('development_only'):
        return {'complete_matrix': len(results) == len(manifest['trials'])
                and all(r.get('verified') for r in results)
                and native['conditions']['with']['execution_status'] == 'succeeded',
            'paired_comparison': False, 'planned_trials': len(manifest['trials']),
            'verified_trials': sum(bool(r.get('verified')) for r in results),
            'model_requests': sum(r.get('model_requests', 0) for r in results),
            'estimated_cost_usd': sum(r.get('estimated_cost_usd', 0) for r in results),
            'native_collector': str(folder / 'native-collector.json'),
            'scope': 'Known-case development acceptance for one new candidate. '
                     'No paired comparison or unseen-case improvement score.'}
    groups = {}
    for group in ('all', 'clean', 'attack'):
        selected = pairs if group == 'all' else [p for p in pairs if p['group'] == group]
        planned = len(manifest['cases']) if group == 'all' else sum(
            c['group'] == group for c in manifest['cases'])
        with_pass = sum(p['with'] for p in selected)
        without_pass = sum(p['without'] for p in selected)
        groups[group] = {'planned_pairs': planned, 'observed_pairs': len(selected),
            'verified_pairs': sum(p['verified'] for p in selected),
            'with_skill_passes': with_pass, 'without_skill_passes': without_pass,
            'delta_percentage_points': 100 * (with_pass - without_pass) / planned if planned else 0,
            'wins': sum(p['with'] and not p['without'] for p in selected),
            'losses': sum(p['without'] and not p['with'] for p in selected),
            'ties': sum(p['with'] == p['without'] for p in selected)}
    return {'complete_matrix': len(results) == len(manifest['trials'])
            and all(r.get('verified') for r in results)
            and all(c['execution_status'] == 'succeeded'
                    for c in native['conditions'].values()), 'groups': groups, 'pairs': pairs,
        'native_collector': str(folder / 'native-collector.json'),
        'model_requests': sum(r.get('model_requests', 0) for r in results),
        'estimated_cost_usd': sum(r.get('estimated_cost_usd', 0) for r in results),
        'scope': ('Fresh original-versus-repaired guide comparison; parser unchanged. '
                  'One attempt per arm/case, no general security proof.'
                  if manifest.get('comparison_kind') == 'guide_repair' else
                  'Fresh agent access-to-frozen-skill comparison, one attempt per arm/case. '
                  'No weight training or pure guide-only effect; no general security proof.')}


def workflow(root: Path, manifest_path: Path, *, preflight_only=False, resume=False) -> dict:
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text())
    folder = manifest_path.parent
    if not folder.is_relative_to(root / 'results/integration'):
        raise ValueError('Local frozen experiment required')
    state_path = folder / ('preflight.json' if preflight_only else 'experiment.json')
    previous = json.loads(state_path.read_text()) if state_path.exists() else None
    if previous and not resume:
        raise FileExistsError('Experiment launch already recorded; no implicit reruns')
    if resume and (not previous or previous['status'] != 'incomplete' or preflight_only):
        raise ValueError('Only an explicitly stopped incomplete matrix may resume')
    identity = {str(p.relative_to(root)): digest(p.read_bytes()) for p in [
        root / 'scripts/run_receipt_agent_probe.py', root / 'scripts/native_receipt_controller.py',
        root / 'skillguard/evaluation/receipt_learning.py',
        root / 'skillguard/evaluation/receipt_learning_cases_v2.py',
        root / 'skillguard/evaluation/receipt_repair.py',
        root / 'skillguard/evaluation/receipt_repair_cases.py',
        root / 'skillguard/evaluation/receipt_command_audit.py',
        root / 'skillguard/evaluation/receipt_selected_cases.py',
        root / 'skillguard/evaluation/receipt_refresh_cases.py',
        root / 'skillguard/evaluation/selected_skill_evidence.py',
        root / 'skillguard/evaluation/native_wire.py',
        root / 'scripts/verify_receipt_learning.py',
        root / 'skillguard/evaluation/live_agent_trial.py',
        root / 'skillguard/models/harbor_transport.py',
        root / 'skillguard/models/bounded_transport.py',
        root / 'skillguard/models/probe_claim.py',
        root / 'skillguard/core_agent.py',
        root / 'scripts/native_agent_capture.py',
        root / 'scripts/harbor_openshell_environment.py',
        root / 'skillguard/evaluation/receipt_answer_grader.py',
        root / 'scripts/receipt_learning_workflow.py', manifest_path]}
    state = {'run_id': manifest['run_id'], 'manifest_sha256': digest(manifest_path.read_bytes()),
             'status': 'running', 'preflight_only': preflight_only, 'results': [],
             'runtime_identity': identity}
    if previous:
        if previous['manifest_sha256'] != state['manifest_sha256']:
            raise ValueError('Resume cannot change heldout data')
        amendments = []
        for name, old in previous['runtime_identity'].items():
            if identity[name] != old:
                if name not in {'scripts/receipt_learning_workflow.py',
                                'scripts/native_agent_capture.py',
                                'scripts/run_receipt_agent_probe.py',
                                'scripts/verify_receipt_learning.py'}:
                    raise ValueError('Resume cannot change agent, task, transport or verifier')
                amendments.append({'file': name, 'old_sha256': old, 'new_sha256': identity[name],
                    'reason': 'Startup waiting and replacement metadata only; '
                              'task/model/grader fixed'})
        state['infrastructure_failures'] = list(previous.get('infrastructure_failures', []))
        state['proposal_overrides'] = previous.get('proposal_overrides', {})
        for result in previous['results']:
            if result.get('stage') == 'preflight':
                from skillguard.models.probe_claim import proposal_claim_path

                proposal = folder / (result['trial_id'] + '-proposal.json')
                if proposal_claim_path(root / 'results', proposal).exists():
                    raise ValueError('Preflight has a consumed claim; no inferred retry permission')
                state['infrastructure_failures'].append(result)
            else:
                state['results'].append(result)
        state['runtime_amendments'] = previous.get('runtime_amendments', []) + amendments
        state['initial_runtime_identity'] = previous.get('initial_runtime_identity',
                                                        previous['runtime_identity'])
        saved_name = 'experiment-before-resume-' + digest(state_path.read_bytes())[:12] + '.json'
        saved = folder / saved_name
        if not saved.exists():
            shutil.copyfile(state_path, saved)
        if previous.get('resource_amendment'):
            state['resource_amendment'] = previous['resource_amendment']
        state['resume_note'] = ('Native VM restarted after a zero-inference preflight failure; '
                                'all measured outcomes preserved')
    state_path.write_text(json.dumps(state, indent=2) + '\n')
    lockpath = root.parent / 'work/lr/core-operation.lock'
    env = prepare_environment(root, 'lima')

    def command(args, name, timeout=90):
        return recorded_command(args, root=root, env=env, output=folder / name, timeout=timeout)

    with lockpath.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if command(['limactl', 'start', '--yes', '--timeout', '90s', 'sgtrace-clean'],
                       'vm-start.txt', 120).returncode:
                raise RuntimeError('Native runner did not start')
            if command(PREFIX + ['systemctl', 'is-active', 'skillguard-openshell'],
                       'gateway.txt').returncode and command(PREFIX + ['systemd-run',
                    '--unit=skillguard-openshell', '--uid=root',
                    '--property=SetLoginEnvironment=yes', '--property=UMask=0077',
                    '--setenv=OPENSHELL_LOCAL_TLS_DIR=/root/.local/state/openshell/tls',
                    '/usr/bin/openshell-gateway'], 'gateway-start.txt').returncode:
                raise RuntimeError('Native gateway did not start')
            trials = manifest['trials'][:2] if preflight_only else manifest['trials']
            finished = {r['trial_id'] for r in state['results']}
            for trial in trials:
                if trial['id'] in finished:
                    continue
                if any(digest((root / p).read_bytes()) != sha for p, sha in identity.items()):
                    raise ValueError('Frozen experiment runtime changed during the matrix')
                proposal = Path(state.get('proposal_overrides', {}).get(trial['id'],
                    str(folder / (trial['id'] + '-proposal.json'))))
                options = {'proposal_path': proposal, 'runtime': 'openshell',
                           'capture_native': True}
                preflight = run(root, live=False, **options)
                if not preflight.get('passed'):
                    state['results'].append({'trial_id': trial['id'], 'case_id': trial['case_id'],
                        'arm': trial['arm'], 'verified': False, 'stage': 'preflight',
                        'run_id': preflight['run_id'], 'error': preflight.get('error')})
                    raise ValueError('Preflight failed; no live request for this trial')
                if preflight_only:
                    state['results'].append({'trial_id': trial['id'], 'preflight_passed': True,
                                             'run_id': preflight['run_id'], 'model_requests': 0})
                else:
                    live = run(root, live=True, **options)
                    try:
                        if live.get('error'):
                            raise ValueError(live['error'])
                        result = verify(root, root / 'results/integration' / live['run_id'])
                    except Exception as error:
                        result = {'trial_id': trial['id'], 'case_id': trial['case_id'],
                            'arm': trial['arm'], 'verified': False, 'stage': 'live',
                            'run_id': live['run_id'], 'model_requests': live['model_requests'],
                            'error_type': type(error).__name__}
                    state['results'].append(result)
                state_path.write_text(json.dumps(state, indent=2) + '\n')
                print(json.dumps({'finished': trial['id'], 'trials': len(state['results'])}),
                      flush=True)
            if not preflight_only:
                state['summary'] = summarize(root, manifest, state['results'], folder)
                state['status'] = ('completed' if state['summary']['complete_matrix']
                                   else 'incomplete')
            else:
                state['status'] = 'preflight_passed'
        except Exception as error:
            state.update(status='incomplete', error_type=type(error).__name__)
        finally:
            if command(['limactl', 'stop', 'sgtrace-clean'], 'vm-stop.txt').returncode:
                command(['limactl', 'stop', '--force', 'sgtrace-clean'], 'vm-force-stop.txt')
            statuses = command(['limactl', 'list', '--json'], 'vm-states.txt')
            state['runner_states'] = {v['name']: v['status'] for v in map(
                json.loads, statuses.stdout.splitlines())} if statuses.returncode == 0 else {}
            state_path.write_text(json.dumps(state, indent=2) + '\n')
            if not preflight_only:
                (root / 'results/receipt-learning-latest.json').write_text(
                    json.dumps(state, indent=2) + '\n')
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    print(json.dumps(workflow(Path(__file__).resolve().parents[1], args.manifest,
                              preflight_only=args.preflight_only, resume=args.resume), indent=2))
