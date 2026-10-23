"""Calibrate authored BYOT graders using installed Harbor oracle, never an LLM.

The native harness owns container creation, execution, verification and cleanup.
Reference and deliberately wrong solutions test grading, not agent resistance.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import shutil
import subprocess
import tarfile
import uuid
from pathlib import Path

from scripts.run_native_evaluation import PREFIX
from skillguard.evaluation.receipt_answer_grader import grade_answer
from skillguard.review.snapshot import artifact_tree_digest, digest

GUEST = '''import json, pathlib, subprocess, sys, tarfile
root=pathlib.Path(sys.argv[1]); root.mkdir(mode=0o700)
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:
    archive.extractall(root,filter='data')
command=['/opt/skillguard-harbor/bin/harbor','run','-p',str(root/'tasks'),
    '-o',str(root/'jobs'),'--job-name','domain-calibration','-a','oracle',
    '--env','docker','-n','1','-k','1','-r','0','--delete','--quiet',
    '--artifact','/workspace/out',
    '--artifact','/workspace/skills/receipt-organizer/scripts/parse_receipt.py']
with (root/'harbor-output.txt').open('w') as log:
    result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=900)
(root/'command.json').write_text(json.dumps({'command':command,'returncode':result.returncode}))
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:
    if (root/'jobs').exists():archive.add(root/'jobs',arcname='jobs')
    archive.add(root/'harbor-output.txt',arcname='harbor-output.txt')
    archive.add(root/'command.json',arcname='command.json')
'''


def extract(raw: bytes, target: Path, *, max_bytes: int = 50 * 1024**2):
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe native calibration artifact')
            if member.isdir():
                continue
            total += member.size
            if total > max_bytes:
                raise ValueError('Native calibration artifact bound exceeded')
            source = archive.extractfile(member)
            assert source is not None
            destination = target / path
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.write_bytes(source.read())
            destination.chmod(0o600)


def verify_trial(trial: dict, trial_root: Path, expected: dict, parser_sha: str) -> dict:
    contract = expected['contract']
    agent = trial.get('config', {}).get('agent', {})
    environment = trial.get('config', {}).get('environment', {})
    if (trial.get('exception_info') is not None or not trial.get('finished_at')
            or agent.get('name') != 'oracle'
            or agent.get('model_name') is not None or agent.get('env') != {}
            or environment.get('type') != 'docker' or environment.get('env') != {}
            or environment.get('mounts') is not None
            or trial.get('agent_info', {}).get('model_info') is not None):
        raise ValueError('Native oracle calibration identity/scope differs')
    source = trial_root / 'artifacts/parse_receipt.py'
    if digest(source.read_bytes()) != parser_sha:
        raise ValueError('Native collected parser differs from frozen source')
    raw = (trial_root / 'artifacts/out/answer.json').read_text()
    reward = json.loads((trial_root / 'verifier/custom_reward.json').read_text())
    recomputed = grade_answer(raw, contract)
    native_score = trial.get('verifier_result', {}).get('rewards', {}).get('overall')
    if (json.dumps(reward, sort_keys=True) != json.dumps(recomputed, sort_keys=True)
            or recomputed['overall'] != expected['expected_score']
            or type(native_score) is not float or native_score != recomputed['overall']):
        raise ValueError('Native calibration reward differs from domain recomputation')
    if (expected['variant'] == 'reference' and expected['reference_input'] is not None
            and (trial_root / 'artifacts/out/input.txt').read_text()
            != expected['reference_input']):
        raise ValueError('Native reference input changed')
    return {'case_id': expected['case_id'], 'provenance': expected['provenance'],
            'variant': expected['variant'], 'score': recomputed['overall'],
            'answer_sha256': digest(raw.encode()), 'parser_sha256': parser_sha,
            'native_trial': str(trial_root / 'result.json')}


def calibrate(root: Path, preparation: Path):
    prepared = json.loads(preparation.read_text())
    parent = json.loads(Path(prepared['preparation']).read_text())
    from scripts.learned_candidate_image import candidate_payload

    candidate_payload(root, Path(prepared['preparation']))
    folder = root / 'results/integration' / f'receipt-task-calibration-{uuid.uuid4().hex[:8]}'
    folder.mkdir(mode=0o700)
    tasks = folder / 'tasks'
    tasks.mkdir()
    expectations = {}
    for item in prepared['tasks']:
        source = Path(item['task'])
        if artifact_tree_digest(source) != item['task_sha256']:
            raise ValueError('Prepared native domain task changed')
        reference = json.loads((source / 'solution/reference.json').read_text())
        for variant in ('reference', 'wrong_answer'):
            name = item['provenance'] + '-' + item['case_id'] + '-' + variant
            task = tasks / name
            shutil.copytree(source, task)
            if variant == 'wrong_answer':
                wrong = copy.deepcopy(reference['contract']['expected'])
                if wrong['receipt'] is None:
                    wrong['receipt'] = {}  # Unrelated requests must not become receipts.
                else:
                    wrong['receipt']['total'] = 0.0
                wrong['question'] = ('Please clarify?' if reference['contract']['ask'] else None)
                (task / 'solution/wrong.json').write_text(json.dumps(wrong))
                (task / 'solution/solve.sh').write_text('#!/bin/sh\nset -eu\n'
                    'cp /solution/wrong.json /workspace/out/answer.json\n')
            expectations[name] = {'case_id': item['case_id'], 'provenance': item['provenance'],
                'variant': variant, 'expected_score': 1.0 if variant == 'reference' else 0.0,
                'contract': reference['contract'], 'reference_input': reference['input'],
                'task_sha256': artifact_tree_digest(task)}
    (folder / 'expectations.json').write_text(json.dumps(expectations, indent=2) + '\n')
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as bundle:
        bundle.add(tasks, arcname='tasks')
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'TMPDIR', 'LANG') if key in os.environ}
    env['LIMA_HOME'] = str(root.parent / 'work/lr')
    report = {'run_id': folder.name, 'preparation': str(preparation),
        'candidate_sha256': parent['candidate_sha256'], 'parser_sha256': parent['parser_sha256'],
        'dataset_sha256': prepared['dataset_sha256'], 'model_calls': 0,
        'agent_execution': False, 'live_agent_cases_executed': 0, 'complete': False,
        'activation_permitted': False, 'skill_lift': None, 'calibration_passed': False,
        'scope': 'Native Harbor oracle domain-grader calibration; not AI-agent resistance'}
    try:
        start = subprocess.run(['limactl', 'start', '--yes', '--timeout', '90s', 'sgtrace-clean'],
            env=env, capture_output=True, text=True, timeout=120, check=False)
        (folder / 'vm-start.txt').write_text(start.stdout + start.stderr)
        if start.returncode:
            raise RuntimeError('Native calibration VM failed to start')
        command = PREFIX + ['python3', '-c', GUEST, '/root/skillguard-' + folder.name]
        result = subprocess.run(command, input=archive.getvalue(), capture_output=True,
                                env=env, timeout=1020, check=False)
        (folder / 'transport-stderr.txt').write_bytes(result.stderr)
        (folder / 'native-job.tar').write_bytes(result.stdout)
        if result.returncode:
            raise RuntimeError('Native Harbor calibration transport failed')
        native = folder / 'native-job'
        extract(result.stdout, native)
        if json.loads((native / 'command.json').read_text())['returncode'] != 0:
            raise RuntimeError('Native Harbor command failed')
        trials = [path for path in (native / 'jobs').rglob('result.json')
                  if path.parent.name != 'domain-calibration']
        if len(trials) != len(expectations):
            raise ValueError('Native calibration did not complete every expected trial')
        seen, checks = set(), []
        for path in trials:
            trial = json.loads(path.read_text())
            name = Path(trial['config']['task']['path']).name
            if name not in expectations or name in seen:
                raise ValueError('Unexpected or duplicate native calibration trial')
            checks.append(verify_trial(trial, path.parent, expectations[name],
                                       parent['parser_sha256']))
            seen.add(name)
        for name, expected in expectations.items():
            if artifact_tree_digest(tasks / name) != expected['task_sha256']:
                raise ValueError('Calibrated native task changed during execution')
        candidate_payload(root, Path(prepared['preparation']))
        report.update(calibration_passed=True, oracle_trials=len(checks), trials=checks,
            reference_solutions_accepted=8, wrong_answers_rejected=8,
            native_job_archive_sha256=digest(result.stdout),
            limitations=prepared['limitations'])
    except Exception as error:
        report['error'] = str(error)
    finally:
        stop = subprocess.run(['limactl', 'stop', '--yes', 'sgtrace-clean'], env=env,
            capture_output=True, text=True, timeout=120, check=False)
        (folder / 'vm-stop.txt').write_text(stop.stdout + stop.stderr)
        report['vm_stopped'] = stop.returncode == 0
        if stop.returncode:
            report['error'] = 'Native calibration VM cleanup failed'
            report['calibration_passed'] = False
        (folder / 'execution.json').write_text(json.dumps(report, indent=2) + '\n')
        (root / 'results/receipt-task-calibration-latest.json').write_text(
            json.dumps(report, indent=2) + '\n')
    return report


def persist(root: Path, execution: Path) -> dict:
    """Recheck collected trials with current verification before private persistence."""
    from scripts.learned_candidate_image import candidate_payload
    from skillguard.review.store import ReviewStore

    report = json.loads(execution.read_text())
    if not report.get('calibration_passed') or not report.get('vm_stopped') or report.get('error'):
        raise ValueError('Incomplete native calibration cannot be persisted as success')
    folder = execution.parent
    preparation = Path(report['preparation'])
    prepared = json.loads(preparation.read_text())
    parent = json.loads(Path(prepared['preparation']).read_text())
    candidate_payload(root, Path(prepared['preparation']))
    expectations = json.loads((folder / 'expectations.json').read_text())
    native = folder / 'native-job'
    if digest((folder / 'native-job.tar').read_bytes()) != report['native_job_archive_sha256']:
        raise ValueError('Native calibration archive changed')
    pack, parser = {}, None
    for trial_path in (native / 'jobs').rglob('result.json'):
        if trial_path.parent.name == 'domain-calibration':
            continue
        trial = json.loads(trial_path.read_text())
        name = Path(trial['config']['task']['path']).name
        if name not in expectations or name in pack:
            raise ValueError('Unexpected or duplicate collected calibration trial')
        expected = expectations[name]
        verify_trial(trial, trial_path.parent, expected, parent['parser_sha256'])
        task = folder / 'tasks' / name
        if artifact_tree_digest(task) != expected['task_sha256']:
            raise ValueError('Native calibration task changed after execution')
        parser = (trial_path.parent / 'artifacts/parse_receipt.py').read_bytes()
        pack[name] = {'trial': trial,
            'contract_json': (task / 'tests/contract.json').read_text(),
            'answer': (trial_path.parent / 'artifacts/out/answer.json').read_text(),
            'reward': json.loads((trial_path.parent / 'verifier/custom_reward.json').read_text()),
            'parser_sha256': digest(parser)}
    if set(pack) != set(expectations) or parser is None:
        raise ValueError('Missing collected native calibration trial')
    artifacts = {'preparation.json': preparation.read_bytes(), 'parser.py': parser,
                 'native-trials.json': json.dumps(pack, sort_keys=True).encode()}
    stored_report = {**report, 'artifacts': {k:digest(v) for k, v in artifacts.items()}}
    store = ReviewStore(Path(parent['store']))
    event = store.record_domain_grader_calibration(parent['review_id'],
        report=json.dumps(stored_report).encode(), artifacts=artifacts)
    report['stored_calibration'] = event['data']
    report['decision'] = store.decide(parent['review_id'])
    execution.write_text(json.dumps(report, indent=2) + '\n')
    (root / 'results/receipt-task-calibration-latest.json').write_text(
        json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preparation', type=Path, required=True)
    args = parser.parse_args()
    result = calibrate(Path(__file__).resolve().parents[1], args.preparation)
    if result['calibration_passed'] and result['vm_stopped']:
        root = Path(__file__).resolve().parents[1]
        result = persist(root, root / 'results/integration' / result['run_id'] / 'execution.json')
    print(json.dumps(result, indent=2))
    if not result['calibration_passed'] or not result['vm_stopped']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
