"""One native Harbor receipt trial, with offline confinement before live use."""
from __future__ import annotations

import argparse
import csv
import errno
import gzip
import io
import json
import os
import shutil
import subprocess
import tarfile
import tomllib
import uuid
from pathlib import Path

from scripts.calibrate_receipt_agent_tasks import extract
from scripts.native_receipt_controller import FAKE_KEY
from scripts.run_native_evaluation import PREFIX
from skillguard.evaluation.receipt_answer_grader import grade_answer
from skillguard.models.bounded_transport import probe_request_limit
from skillguard.models.probe_claim import claim_probe, proposal_claim_path, reconcile_probe
from skillguard.models.spending_policy import proposal_cap
from skillguard.review.snapshot import artifact_tree_digest, digest


def require_free_storage(root: Path) -> None:
    if shutil.disk_usage(root).free < 2 * 1024**3:
        raise OSError(errno.ENOSPC, 'Native review requires at least 2 GiB free host storage')


def archive_native_transport(folder: Path, raw: bytes) -> dict:
    target = folder / 'native-job.tar.gz'
    if target.exists() or target.is_symlink():
        raise FileExistsError('Preserve the previous native transport archive')
    with (target.open('xb') as output,
          gzip.GzipFile(fileobj=output, mode='wb', compresslevel=1, mtime=0) as compressed):
        compressed.write(raw)
    original_sha = digest(raw)
    import hashlib

    with gzip.open(target, 'rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != original_sha:
            raise ValueError('Native transport compression changed bytes')
    proof = {'archive': target.name, 'original_sha256': original_sha,
             'original_bytes': len(raw), 'compressed_bytes': target.stat().st_size,
             'lossless_verified': True}
    (folder / 'transport-storage.json').write_text(json.dumps(proof, indent=2) + '\n')
    return proof

BOOT = '''import pathlib,sys,tarfile
root=pathlib.Path(sys.argv[1]); root.mkdir(mode=0o700)
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:
 archive.extractall(root,filter='data')
'''


def prepared_task(root: Path, folder: Path, proposal_path: Path | None = None
                  ) -> tuple[Path, dict, dict]:
    proposal_path = proposal_path or root / 'results/receipt-live-probe-proposal.json'
    proposal = json.loads(proposal_path.read_text())
    if proposal.get('security_trial'):
        from skillguard.evaluation.security_probe import prepare_task

        return prepare_task(root, folder, proposal)
    if proposal.get('learning_trial'):
        from skillguard.evaluation.receipt_learning import prepare_task

        return prepare_task(root, folder, proposal)
    item = proposal['task']
    source = Path(item['task'])
    if artifact_tree_digest(source) != item['task_sha256']:
        raise ValueError('Authorized native task changed')
    for name, sha in proposal['reviewed_files'].items():
        if digest(Path(name).read_bytes()) != sha:
            raise ValueError('Authorized exported bytes changed')
    from scripts.learned_candidate_image import candidate_payload

    tasks = json.loads((root / 'results/receipt-agent-tasks-latest.json').read_text())
    selected = None
    if proposal.get('review_target'):
        from skillguard.core_agent import selected_candidate

        selected = selected_candidate(root, proposal['review_target'])
        tasks = {**tasks, **selected}
    else:
        candidate_payload(root, Path(tasks['preparation']))
    reference = json.loads((source / 'solution/reference.json').read_text())
    task = folder / 'task'
    shutil.copytree(source, task)
    if selected:
        target = task / 'environment/skills/receipt-organizer'
        shutil.rmtree(target)
        shutil.copytree(selected['snapshot'], target)
    protocol = proposal.get('instruction_protocol')
    if protocol is not None:
        from skillguard.evaluation.agent_task_protocol import SUPPORTED_PROTOCOLS, stage

        if protocol not in SUPPORTED_PROTOCOLS or item['case_id'] != 'receipt-organizer-001':
            raise ValueError('Unsupported trusted receipt-task protocol')
        stage(task, protocol)
    discovery = proposal.get('native_skill_discovery', False)
    if type(discovery) is not bool:
        raise ValueError('Native skill discovery must be an explicit boolean')
    if discovery and tomllib.loads((task / 'task.toml').read_text()).get(
            'environment', {}).get('skills_dir') != '/workspace/skills':
        raise ValueError('Reviewed task must configure native skill discovery')
    # Oracle answers are not available to the supported live agent.
    shutil.rmtree(task / 'solution')
    dockerfile = task / 'environment/Dockerfile'
    original = dockerfile.read_text()
    dockerfile.write_text(original.replace('FROM python:3.12-slim\n',
        'FROM python:3.12-slim\nRUN apt-get update && apt-get install -y --no-install-recommends '
        'tmux bash && rm -rf /var/lib/apt/lists/*\n', 1))
    # Selected source must remain root-owned and immutable to the agent UID.
    dockerfile.write_text(dockerfile.read_text().rsplit('USER 1000:1000', 1)[0] +
        'RUN chown -R root:root /workspace/skills && find /workspace/skills -type d '
        '-exec chmod 555 {} + && find /workspace/skills -type f -exec chmod 444 {} +\n'
        'USER 1000:1000\n')
    return task, reference, tasks


def verify_enforced_prerequisites(root: Path, proposal: dict, preflight: dict):
    if preflight.get('runtime') != 'openshell' or preflight.get('capture_native') is not True:
        raise ValueError('Fresh captured OpenShell preflight required')
    if proposal.get('review_target'):
        # Recheck this host's current source-bound native/static review. A
        # different machine's historical replay does not provide this credit.
        from skillguard.core_agent import selected_candidate

        selected_candidate(root, proposal['review_target'])
    else:
        comparison = json.loads((root / 'results/receipt-agent-workflow-latest.json').read_text())
        if not comparison.get('diagnostic_passed'):
            raise ValueError('Native recorded enforcement and captured preflight required')


def run(root: Path, *, live: bool, recorded_from: Path | None = None,
        proposal_path: Path | None = None, capture_native: bool = False,
        runtime: str = 'docker') -> dict:
    require_free_storage(root)
    if runtime not in {'docker', 'openshell'}:
        raise ValueError('Unsupported native runtime')
    if live and recorded_from is not None:
        raise ValueError('Recorded responses cannot run in live mode')
    if live and capture_native and runtime != 'openshell':
        raise ValueError('Fresh native capture is restricted to the verified OpenShell profile')
    default = root / 'results/receipt-live-probe-proposal.json'
    proposal_path = (proposal_path or default).resolve()
    if not proposal_path.is_relative_to(root / 'results'):
        raise ValueError('Probe proposal must be an operator-owned local result')
    proposal = json.loads(proposal_path.read_text())
    if live and runtime == 'openshell' and (
            proposal.get('runtime') != 'openshell' or not capture_native):
        raise ValueError('Fresh OpenShell execution requires a scoped proposal and native capture')
    proposal_sha = digest(proposal_path.read_bytes())
    aggregate_cap = proposal_cap(root / 'results', proposal.get('aggregate_cap_usd', .75))
    limit = probe_request_limit(proposal.get('maximum_model_requests'),
                                proposal.get('app_execution_profile'))
    if proposal.get('agent_timeout_sec') is not None and not (
            limit == 8 and proposal.get('review_target')
            and proposal.get('agent_timeout_sec') == 600
            and proposal.get('provider_timeout_sec') == 60):
        raise ValueError('Unsupported prospective cloud deadline profile')
    if limit == 8 and not proposal.get('review_target'):
        raise ValueError('Eight-request app trial requires a source-bound review')
    if proposal.get('learning_trial'):
        from skillguard.evaluation.receipt_learning import load_trial

        load_trial(root, proposal)
    if limit >= 6 and not (runtime == 'openshell' and proposal.get('frontmatter_compat') is True
                          and (proposal.get('native_skill_discovery') is True
                               or proposal.get('learning_trial'))):
        raise ValueError('Six-request probe requires the scoped native compatibility profile')
    claim_path = proposal_claim_path(root / 'results', proposal_path)
    if proposal.get('security_trial'):
        from skillguard.evaluation.security_probe import load

        load(root, proposal)
    if proposal_path != default and not proposal.get('learning_trial') and not proposal.get(
            'security_trial'):
        previous = json.loads(default.read_text())
        for field in ('task', 'maximum_output_tokens_per_request',
                      'aggregate_cap_usd', 'thinking_enabled', 'exports', 'excluded',
                      'reviewed_files', 'prerequisites'):
            if field == 'reviewed_files' and proposal.get('review_target'):
                continue
            if field == 'aggregate_cap_usd' and proposal.get('review_target'):
                continue  # Independently checked against the operator-owned spending policy.
            if proposal.get(field) != previous.get(field):
                raise ValueError('Continuation proposal expands the approved export/bounds')
    if live and claim_path.exists():
        raise FileExistsError('The approved one-probe request allowance has been consumed')
    folder = root / 'results/integration' / ('receipt-agent-' + uuid.uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    task, reference, tasks = prepared_task(root, folder, proposal_path)
    if runtime == 'openshell':
        dockerfile = task / 'environment/Dockerfile'
        dockerfile.write_text(dockerfile.read_text() + '\nUSER root\n'
            'RUN groupadd -g 1000 sandbox && useradd -u 1000 -g 1000 -m sandbox\n'
            'RUN mkdir -p /sandbox /tests /logs/agent /logs/verifier /logs/artifacts && '
            'chown -R 1000:1000 /sandbox /tests /logs\n'
            'USER 1000:1000\nWORKDIR /sandbox\nCMD ["sleep", "3600"]\n')
        config = task / 'task.toml'
        config.write_text(config.read_text().replace('user = "root"', 'user = "1000:1000"')
                          .replace('[environment]\n', '[environment]\nworkdir = "/sandbox"\n'))
    mode = 'live' if live else 'recorded' if recorded_from is not None else 'offline'
    integration_files = ('scripts/native_receipt_controller.py',
        'scripts/run_receipt_agent_probe.py', 'skillguard/models/harbor_transport.py',
        'skillguard/models/bounded_transport.py', 'skillguard/models/recorded_responses.py',
        'scripts/native_agent_capture.py', 'scripts/harbor_openshell_environment.py',
        'scripts/native_harbor_compat.py')
    integration_files += ('skillguard/evaluation/agent_task_protocol.py',)
    if proposal.get('security_trial'):
        integration_files += ('skillguard/evaluation/security_probe.py',)
    if proposal.get('learning_trial'):
        integration_files += ('skillguard/evaluation/receipt_learning.py',
                              'skillguard/evaluation/receipt_learning_cases_v2.py',
                              'skillguard/evaluation/receipt_repair.py',
                              'skillguard/evaluation/receipt_repair_cases.py')
        integration_files += ('skillguard/evaluation/receipt_selected_cases.py',
                              'skillguard/evaluation/receipt_refresh_cases.py')
    report = {'run_id': folder.name, 'proposal_path': str(proposal_path), 'mode': mode,
        'native_agent': 'terminus-2',
        'proposal_sha256': proposal_sha, 'capture_native': capture_native, 'runtime': runtime,
        'native_skill_discovery': proposal.get('native_skill_discovery', False),
        'frontmatter_compat': proposal.get('frontmatter_compat', False),
        'maximum_model_requests': limit,
        'app_execution_profile': proposal.get('app_execution_profile'),
        'agent_timeout_sec': proposal.get('agent_timeout_sec'),
        'provider_timeout_sec': proposal.get('provider_timeout_sec'),
        'aggregate_cap_usd': aggregate_cap,
        'reservation_profile': proposal.get('reservation_profile', 'legacy'),
        'instruction_protocol': proposal.get('instruction_protocol'),
        'require_skill_use_proof': proposal.get('require_skill_use_proof', False),
        'controller_sha256': digest((root / 'scripts/native_receipt_controller.py').read_bytes()),
        'integration_sha256': {p: digest((root / p).read_bytes()) for p in integration_files},
        'task_sha256': artifact_tree_digest(task), 'candidate_sha256': tasks['candidate_sha256'],
        'parser_sha256': tasks['parser_sha256'] if 'parser_sha256' in tasks else
            json.loads(Path(tasks['preparation']).read_text())['parser_sha256'],
        'review_target': proposal.get('review_target'),
        'learning_trial': proposal.get('learning_trial'),
        'security_trial': proposal.get('security_trial'),
        'case_id': proposal['task']['case_id'], 'model_requests': 0,
        'live_agent_cases_executed': 0, 'complete': False, 'activation_permitted': False,
        'skill_lift': None, 'passed': False}
    if recorded_from is not None:
        original = json.loads((recorded_from / 'report.json').read_text())
        if original['mode'] != 'live' or original['candidate_sha256'] != tasks['candidate_sha256']:
            raise ValueError('Recorded native candidate/mode differs')
        recorded = folder / 'recorded'
        recorded.mkdir()
        original_native = recorded_from / 'native-job'
        items = []
        for row in csv.DictReader((original_native / 'cost.csv').open()):
            source = original_native / 'responses' / (row['call_id'] + '.json')
            if source.is_file():
                raw = source.read_bytes()
                items.append({'name': source.name, 'sha256': digest(raw)})
                (recorded / source.name).write_bytes(raw)
        manifest = {'source_report_sha256': digest((recorded_from / 'report.json').read_bytes()),
                    'source_run_id': original['run_id'], 'responses': items}
        (recorded / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        from skillguard.models.recorded_responses import load_responses

        load_responses(recorded)
        report['recorded_response_provenance'] = manifest
        report['scope'] = 'Offline execution of retained replies; no fresh agent evaluation'
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'LANG') if k in os.environ}
    env['LIMA_HOME'] = str(root.parent / 'work/lr')
    deploy = '/root/skillguard-controller-' + uuid.uuid4().hex[:8]
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as bundle:
        for name in ('skillguard/__init__.py', 'skillguard/models/__init__.py',
            'skillguard/models/bounded_transport.py', 'skillguard/models/harbor_transport.py',
            'skillguard/models/recorded_responses.py',
            'skillguard/evaluation/__init__.py', 'skillguard/evaluation/agent_task_protocol.py',
            'skillguard/evaluation/receipt_task_contracts.py',
            'skillguard/evaluation/receipt_learning.py',
            'skillguard/evaluation/receipt_learning_cases_v2.py',
            'skillguard/evaluation/receipt_repair.py',
            'skillguard/evaluation/receipt_repair_cases.py',
            'skillguard/evaluation/receipt_selected_cases.py',
            'skillguard/evaluation/receipt_refresh_cases.py',
            'skillguard/evaluation/security_probe.py',
            'scripts/native_receipt_controller.py', 'scripts/native_agent_capture.py',
            'scripts/native_harbor_compat.py'):
            bundle.add(root / name, arcname=name)
        for name in ('scripts/harbor_openshell_environment.py', 'skillguard/review/__init__.py',
                     'skillguard/review/snapshot.py'):
            bundle.add(root / name, arcname=name)
    result = subprocess.run(PREFIX + ['python3', '-c', BOOT, deploy],
        input=archive.getvalue(), capture_output=True, env=env, timeout=30, check=True)
    key, ledger_bytes, reservation = FAKE_KEY, (root / 'results/cost_log.csv').read_bytes(), None
    if live:
        if (proposal.get('execution_enabled') is not True
                or proposal.get('status') not in {'authorized_2026_10_06',
                                                 'authorized_2026_10_08',
                                                 'authorized_2026_10_10',
                                                 'authorized_2026_10_22'}):
            raise ValueError('Current single-probe authorization is absent')
        preflight_path = root / 'results/receipt-agent-offline-latest.json'
        preflight = json.loads(preflight_path.read_text())
        if (not preflight['passed'] or preflight['mode'] != 'offline'
                or preflight['task_sha256'] != report['task_sha256']
                or preflight.get('proposal_sha256') != proposal_sha
                or preflight.get('integration_sha256') != report['integration_sha256']
                or preflight['controller_sha256'] != digest(
                    (root / 'scripts/native_receipt_controller.py').read_bytes())):
            raise ValueError('Exact native credential-confinement preflight required')
        if runtime == 'openshell':
            verify_enforced_prerequisites(root, proposal, preflight)
        import httpx
        from dotenv import dotenv_values

        key = dotenv_values(root / '.env')['NEBIUS_API_KEY']
        if not key:
            raise ValueError('Private Nebius credential missing')
        with httpx.Client(trust_env=False, timeout=30) as client:
            catalog = client.get('https://api.tokenfactory.nebius.com/v1/models',
                                 headers={'Authorization': 'Bearer ' + key})
            catalog.raise_for_status()
        from skillguard.models.bounded_transport import MODEL

        if MODEL not in {m['id'] for m in catalog.json()['data']}:
            raise ValueError('Approved model absent from current catalog')
        (folder / 'catalog.json').write_text(json.dumps(catalog.json(), indent=2))
        claim_path.parent.mkdir(exist_ok=True)
        reservation, ledger_bytes = claim_probe(root / 'results/cost_log.csv', claim_path, report)
    baseline = {r['call_id'] for r in csv.DictReader(io.StringIO(ledger_bytes.decode()))}
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as bundle:
        bundle.add(task, arcname='task')
        if recorded_from is not None:
            bundle.add(recorded, arcname='recorded')
        entry = tarfile.TarInfo('cost.csv')
        entry.size = len(ledger_bytes)
        entry.mode = 0o600
        bundle.addfile(entry, io.BytesIO(ledger_bytes))
    controller = ('import sys;sys.path.insert(0,' + repr(deploy) +
                  ');from scripts.native_receipt_controller import main;main()')
    from skillguard.traces.sysdig import SYSDIG_FORMAT

    header = json.dumps({'mode': mode, 'api_key': key, 'capture_native': capture_native,
                         'frontmatter_compat': proposal.get('frontmatter_compat', False),
                         'native_skill_discovery': proposal.get('native_skill_discovery', False),
                         'instruction_protocol': proposal.get('instruction_protocol'),
                         'learning_trial': proposal.get('learning_trial'),
                         'security_trial': proposal.get('security_trial'),
                         'require_skill_use_proof': proposal.get('require_skill_use_proof', False),
                         'maximum_model_requests': limit,
        'app_execution_profile': proposal.get('app_execution_profile'),
        'agent_timeout_sec': proposal.get('agent_timeout_sec'),
        'provider_timeout_sec': proposal.get('provider_timeout_sec'),
                         'aggregate_cap_usd': aggregate_cap,
                         'runtime': runtime,
                         'reservation_profile': report['reservation_profile'],
                         'event_format': SYSDIG_FORMAT}).encode() + b'\n'
    try:
        result = subprocess.run(PREFIX + ['/opt/skillguard-harbor/bin/python', '-c',
            controller, '/root/skillguard-' + folder.name], input=header + archive.getvalue(),
            capture_output=True, env=env, timeout=(1200 if proposal.get('agent_timeout_sec')
                     else 600),
            check=False)
        # Never print or archive returned secret-bearing material.
        if key.encode() in result.stdout or key.encode() in result.stderr:
            raise ValueError('Credential in returned native material; export withheld')
        (folder / 'transport-stderr.txt').write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError('Native controller transport failed')
        report['transport_storage'] = archive_native_transport(folder, result.stdout)
        native = folder / 'native-job'
        extract(result.stdout, native, max_bytes=(512 if proposal.get('agent_timeout_sec')
                else 300 if capture_native else 50) * 1024**2)
        controller_result = json.loads((native / 'controller-result.json').read_text())
        report.update(controller_result)
        if controller_result.get('error_type'):
            report['controller_error_type'] = controller_result['error_type']
            raise RuntimeError('Native controller failed; see retained controller diagnostics')
        if report['native_skill_discovery']:
            requests = json.loads((native / 'requests.json').read_text())
            initial = json.dumps(requests[0].get('messages', []))
            if not all(token in initial for token in ('<available_skills>',
                    '<name>receipt-organizer</name>',
                    '/workspace/skills/receipt-organizer/SKILL.md')):
                raise ValueError('Native initial request did not discover the selected skill')
            if report['frontmatter_compat'] and not (native / 'frontmatter-compat.json').is_file():
                raise ValueError('Native frontmatter compatibility proof missing')
            report['native_skill_discovery_verified'] = True
        if live:
            rows = reconcile_probe(root / 'results/cost_log.csv', reservation,
                                   native / 'cost.csv', baseline, maximum_model_requests=limit,
                                   reservation_profile=report['reservation_profile'],
                                   app_execution_profile=report.get('app_execution_profile'))
            report.update(model_requests=len(rows), estimated_cost_usd=sum(
                float(r['estimated_cost_usd'] or 0) for r in rows),
                unknown_reserved_usd=sum(float(r['reserved_cost_usd'] or 0) for r in rows))
        trials = [p for p in (native / 'jobs').rglob('result.json')
                  if p.parent.name != 'receipt-probe']
        if len(trials) != 1:
            raise ValueError('Expected exactly one native agent trial')
        path = trials[0]
        trial = json.loads(path.read_text())
        report.update(native_trial=str(path), exception_info=trial.get('exception_info'))
        if not (native / 'confinement.json').exists():
            raise ValueError('Native trial failed before credential-confinement verification')
        proof = json.loads((native / 'confinement.json').read_text())
        report.update(native_trial=str(path), exception_info=trial.get('exception_info'),
            confinement=proof, native_reward=(trial.get('verifier_result') or {}).get('rewards'),
            live_agent_trials_started=1 if live else 0)
        trajectory = path.parent / 'agent/trajectory.json'
        if trajectory.exists():
            steps = json.loads(trajectory.read_text())['steps']
            report['native_agent_steps'] = sum(s.get('source') == 'agent' for s in steps)
            report['trajectory_sha256'] = digest(trajectory.read_bytes())
        parser = path.parent / 'artifacts/parse_receipt.py'
        if not report.get('learning_trial') or report['native_skill_discovery']:
            if digest(parser.read_bytes()) != report['parser_sha256']:
                raise ValueError('Native parser artifact differs from frozen source')
            report['parser_preserved'] = True
        else:
            if parser.exists():
                raise ValueError('Baseline unexpectedly collected a skill parser')
            report['parser_preserved'] = None
        if trial.get('exception_info') is not None:
            raise ValueError('Native agent trial failed; no completed domain result')
        answer = path.parent / 'artifacts/out/answer.json'
        raw = answer.read_text() if answer.exists() else None
        score = grade_answer(raw, reference['contract'])
        report.update(recomputed_grade=score, answer_sha256=digest(raw.encode()) if raw else None,
                      completed_domain_cases=1)
        report['passed'] = (proof['passed'] and not trial.get('exception_info')
            and score['overall'] == 1.0 and
            trial['verifier_result']['rewards']['overall'] == 1.0)
        report['live_agent_cases_executed'] = 1 if live and report['model_requests'] else 0
    except Exception as error:
        report['error_type'] = type(error).__name__
        # No unreviewed automatic retry; native errors are evidence, not new permission.
        report['error'] = (str(error) if key not in str(error)
                           else 'Credential-bearing error withheld')
    report['report_path'] = str(folder / 'report.json')
    (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    latest = ('receipt-agent-enforced-live-latest.json' if live and runtime == 'openshell'
              else f'receipt-agent-{mode}-latest.json')
    (root / 'results' / latest).write_text(
        json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--recorded-from', type=Path)
    parser.add_argument('--proposal', type=Path)
    parser.add_argument('--capture-native', action='store_true')
    parser.add_argument('--runtime', choices=['docker', 'openshell'], default='docker')
    args = parser.parse_args()
    result = run(Path(__file__).resolve().parents[1], live=args.live,
                 recorded_from=args.recorded_from, proposal_path=args.proposal,
                 capture_native=args.capture_native, runtime=args.runtime)
    print(json.dumps(result, indent=2))
