"""Package a portable, read-only walkthrough of retained native product evidence."""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from skillguard.core import CoreWorkspace
from skillguard.review.snapshot import digest


def payload(root: Path) -> dict:
    source = root / 'results/security-product-latest.json'
    verification = root / 'results/oct23-security-product-verification.json'
    flow, verified = json.loads(source.read_bytes()), json.loads(verification.read_bytes())
    if not flow['passed'] or not verified['passed'] or verified['workflow_run'] != flow['run_id']:
        raise ValueError('Verified product lifecycle required; no synthetic fallback')
    workspace = CoreWorkspace(root, root / 'results/core')
    blocked = workspace.store.get(flow['blocked_review'])
    repaired = workspace.store.get(flow['repaired_review'])
    security = repaired['latest']['security_review']
    if (security['decision'] != 'held' or security['verified_probes'] != 4
            or flow['installed']['security_decision'] != 'operator_approved_hold'):
        raise ValueError('Recorded warning/approval outcome differs; rebuild deliberately')
    design = Path(security['manifest']).read_bytes()
    if digest(design) != security['manifest_sha256']:
        raise ValueError('Generated design changed')
    cases = {c['id']: c for c in json.loads(design)['cases']}
    probes = []
    for probe in security['probes']:
        if (not probe['agent_task_passed'] or probe['private_open_attempts']
                or probe['terminal_fake_canary_disclosure']):
            raise ValueError('Recorded probe is not a completed safe-observation result')
        question = cases[probe['case_id']]['question']
        quoted = re.search(r'"([^"]+)"', question)
        if quoted is None:
            raise ValueError('Exact generated annotation excerpt unavailable')
        probes.append({'id': probe['case_id'], 'run_id': probe['run_id'],
            'annotation_excerpt': quoted.group(1), 'model_requests': probe['model_requests'],
            'completed': probe['agent_completion_confirmed'], 'answer': probe['answer'],
            'private_open_attempts': len(probe['private_open_attempts']),
            'commands': [a['command'] for a in probe['terminal_actions']]})
    observations = {}
    for label, review in (('unsafe', blocked), ('repaired', repaired)):
        view = workspace.security_view(review)
        behavior = review['latest']['core_test']['behavior']
        observations[label] = {'candidate_sha256': review['candidate_sha256'],
            'counts': {k: len(v) for k, v in behavior.items()},
            'functional_passed': view['native_regression']['passed'],
            'private_denials': view['native_regression']['private_denials'],
            'independent_denial_control': 1}
    advice = [*security['previous_model_reviews'], security['model_review']]
    result = {'schema': 'skillguard-recorded-demo-v1', 'recorded_on': '2026-10-23',
        'mode': 'Recorded evidence replay. No live agent, inference or installation actions.',
        'scenario': 'Staged receipt-skill attack using fictional data and a fake private file.',
        'source_workflow': flow['run_id'], 'source_workflow_sha256': digest(source.read_bytes()),
        'verification_sha256': digest(verification.read_bytes()),
        'candidate_sha256': repaired['candidate_sha256'], 'probes': probes,
        'observations': observations,
        'models': [{k: m[k] for k in ('model', 'recommendation', 'explanation')}
                   for m in advice],
        'policy': security['policy']['policy'], 'policy_sha256': security['policy_sha256'],
        'approval': {'decision': flow['approval_outcome'],
            'reason': flow['installed']['operator_reason'],
            'installed_version': flow['installed']['id'],
            'previous_version': flow['original_active']['id'],
            'rollback_verified': sum(s['step'] == 'rollback' and
                s['result']['status'] == 'done' for s in flow['steps']) == 2},
        'budget_at_recording': verified['budget'],
        'recovery': {'earlier_trial_retained_as_incomplete': True,
            'passing_probes_reused': len(verified['reused_verified_probes']),
            'original_forwarded_requests': 6, 'original_responses': 4,
            'claims_reset': False, 'all_unknown_holds_retained_usd': .25},
        'limits': ['Receipt profile only; three generated attack annotations and one control.',
            'Metadata includes setup and verification; not complete skill-only attribution.',
            'Both model verdicts held. Human exception is not a security pass.',
            'Original incomplete trial retained; no fresh independent benchmark claim.',
            'Local OpenShell runtime; cloud sandbox access was unavailable.']}
    raw = json.dumps(result)
    if any(marker in raw for marker in ('/Users/', '/home/', 'NEBIUS_API_KEY', 'csrf')):
        raise ValueError('Private host/session data must not enter the public demo')
    return result


def build(root: Path) -> dict:
    result = payload(root)
    folder = root / 'dist/skillguard-demo'
    folder.mkdir(parents=True, exist_ok=True)
    assets = root / 'skillguard/ui'
    files = {'index.html': (assets / 'demo.html').read_bytes(),
        'demo.js': (assets / 'demo.js').read_bytes(),
        'demo.css': (assets / 'demo.css').read_bytes(),
        'evidence.json': (json.dumps(result, indent=2) + '\n').encode(),
        'LICENSE': (root / 'LICENSE').read_bytes(),
        'README.txt': b'SkillGuard recorded evidence demo. No live model calls or writes.\n'
            b'Serve this directory: python3 -m http.server 8769 --bind 127.0.0.1\n'
            b'Open http://127.0.0.1:8769/ . All scenario data is fictional.\n'
            b'This replay is not the live review backend and is not a security guarantee.\n'}
    provenance = {name: digest(raw) for name, raw in files.items()}
    files['provenance.json'] = (json.dumps(provenance, indent=2) + '\n').encode()
    target = root / 'dist/skillguard-demo.zip'
    if (not folder.resolve().is_relative_to(root.resolve()) or folder.is_symlink()
            or target.is_symlink() or any(p.is_symlink() or not p.is_file()
                or p.name not in files for p in folder.iterdir())):
        raise ValueError('Demo output must contain only regular allowlisted release files')
    for name, raw in files.items():
        (folder / name).write_bytes(raw)
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 23, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    report = {'passed': True, 'command': '.venv/bin/python -m scripts.build_demo',
        'archive': str(target.relative_to(root)), 'sha256': digest(target.read_bytes()),
        'bytes': target.stat().st_size, 'files': provenance,
        'source_workflow': result['source_workflow'], 'public_upload_performed': False,
        'new_model_requests': 0, 'browser_visual_qa': 'unverified'}
    (root / 'results/demo-build.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    print(json.dumps(build(Path(__file__).resolve().parents[1]), indent=2))
