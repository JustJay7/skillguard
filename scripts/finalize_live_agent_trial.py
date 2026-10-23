from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore


def collect_artifacts(root: Path, folder: Path) -> tuple[dict, dict[str, bytes]]:
    report = json.loads((folder / 'report.json').read_text())
    native = folder / 'native-job'
    trial_path = Path(report['native_trial'])
    responses = {p.stem: json.loads(p.read_text()) for p in (native / 'responses').glob('*.json')}
    rows = [r for r in csv.DictReader((native / 'cost.csv').open()) if r['call_id'] in responses]
    answer_path = trial_path.parent / 'artifacts/out/answer.json'
    recovered = {}
    if report.get('answer_export_recovery'):
        from skillguard.evaluation.receipt_output_recovery import checked_answer

        actual, recovered = checked_answer(folder, report)
        if (answer_path.is_symlink() or not answer_path.is_file()
                or answer_path.read_bytes() != actual):
            raise ValueError('Recovered answer differs from its stopped-container source')
    artifacts = {'trial.json': trial_path.read_bytes(),
        'trajectory.json': (trial_path.parent / 'agent/trajectory.json').read_bytes(),
        'requests.json': (native / 'requests.json').read_bytes(),
        'confinement.json': (native / 'confinement.json').read_bytes(),
        'cost-rows.json': json.dumps(rows).encode(),
        'responses.json': json.dumps(responses).encode(),
        'contract.json': (folder / 'task/tests/contract.json').read_bytes(),
        'answer.json': json.dumps({'raw': answer_path.read_text()
                                  if answer_path.exists() else None}).encode()}
    artifacts.update(recovered)
    parser = trial_path.parent / 'artifacts/parse_receipt.py'
    if parser.exists():
        artifacts['parser.py'] = parser.read_bytes()
    if report.get('learning_trial'):
        artifacts['receipt.txt'] = (trial_path.parent / 'artifacts/receipt.txt').read_bytes()
        artifacts['input-proof.json'] = (native / 'input-proof.json').read_bytes()
        artifacts['skill-exposure.json'] = (native / 'skill-exposure.json').read_bytes()
    enforced = report.get('runtime') == 'openshell'
    if report.get('instruction_protocol'):
        artifacts['instruction.md'] = (folder / 'task/instruction.md').read_bytes()
        artifacts['receipt.txt'] = (folder / 'task/environment/input/receipt.txt').read_bytes()
    if report.get('security_trial'):
        artifacts['instruction.md'] = (folder / 'task/instruction.md').read_bytes()
        artifacts['security-design.json'] = (folder / 'task/security-design.json').read_bytes()
    if report.get('require_skill_use_proof'):
        artifacts['guide.md'] = (trial_path.parent / 'artifacts/SKILL.md').read_bytes()
        artifacts['receipt.txt'] = (trial_path.parent / 'artifacts/receipt.txt').read_bytes()
        artifacts['input-proof.json'] = (native / 'input-proof.json').read_bytes()
    if enforced:
        adapter = trial_path.parent / 'environment/openshell'
        artifacts.update({name: (native / 'capture' / name).read_bytes()
            for name in ('capture.json', 'events.jsonl', 'events.scap.gz', 'stats.txt')})
        artifacts.update({name: (adapter / name).read_bytes()
            for name in ('policy.yaml', 'sandbox.json', 'binding.json', 'stopped.json')})
        artifacts['container.json'] = (native / 'container-inspect.json').read_bytes()
        if report.get('frontmatter_compat'):
            artifacts['frontmatter-compat.json'] = (native / 'frontmatter-compat.json').read_bytes()
            artifacts['compat-source.py'] = (root / 'scripts/native_harbor_compat.py').read_bytes()
        environment = folder / 'task/environment'
        artifacts['environment-files.json'] = json.dumps({p.relative_to(environment).as_posix():
            digest(p.read_bytes()) for p in environment.rglob('*') if p.is_file()},
            sort_keys=True).encode()
    report['artifacts'] = {k: digest(v) for k, v in artifacts.items()}
    return report, artifacts


def finalize(root: Path, folder: Path) -> dict:
    report, artifacts = collect_artifacts(root, folder)
    if report.get('security_trial'):
        from skillguard.security_review import finalize_probe

        return finalize_probe(root, folder, report, artifacts)
    enforced = report.get('runtime') == 'openshell'
    tasks = json.loads((root / 'results/receipt-agent-tasks-latest.json').read_text())
    parent = report.get('review_target') or json.loads(Path(tasks['preparation']).read_text())
    store = ReviewStore(Path(parent['store']))
    record = (store.record_core_agent_test if report.get('review_target') else
              store.record_enforced_live_trial if enforced else store.record_live_agent_trial)
    event = record(parent['review_id'],
        report=json.dumps(report).encode(), artifacts=artifacts)
    report['live_trial_evidence'] = event['data']
    report['decision'] = (
        {'decision': 'held', 'activation_permitted': False,
         'reasons': ['Explicit operator approval required for restricted workspace installation']}
        if report.get('review_target') else store.decide(parent['review_id']))
    (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    latest = ('receipt-agent-enforced-live-latest.json' if enforced
              else 'receipt-agent-live-latest.json')
    (root / 'results' / latest).write_text(
        json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    result = finalize(Path(__file__).resolve().parents[1], args.folder.resolve())
    print(json.dumps(result['live_trial_evidence'], indent=2))
