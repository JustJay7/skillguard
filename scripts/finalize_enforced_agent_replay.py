from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore


def finalize(root: Path, folder: Path) -> dict:
    report = json.loads((folder / 'report.json').read_text())
    native = folder / 'native-job'
    trial = Path(report['native_trial'])
    adapter = trial.parent / 'environment/openshell'
    artifacts = {name: (native / 'capture' / name).read_bytes()
                 for name in ('capture.json', 'events.jsonl', 'events.scap.gz', 'stats.txt')}
    artifacts.update({name: (adapter / name).read_bytes()
        for name in ('policy.yaml', 'sandbox.json', 'binding.json', 'stopped.json')})
    artifacts.update({'trial.json': trial.read_bytes(),
        'trajectory.json': (trial.parent / 'agent/trajectory.json').read_bytes(),
        'parser.py': (trial.parent / 'artifacts/parse_receipt.py').read_bytes(),
        'container.json': (native / 'container-inspect.json').read_bytes(),
        'confinement.json': (native / 'confinement.json').read_bytes(),
        'manifest.json': (native / 'recorded/manifest.json').read_bytes(),
        'responses.json': json.dumps({p.name: p.read_text()
            for p in (native / 'recorded').glob('*.json') if p.name != 'manifest.json'}).encode(),
        'contract.json': (folder / 'task/tests/contract.json').read_bytes()})
    environment = folder / 'task/environment'
    artifacts['environment-files.json'] = json.dumps({p.relative_to(environment).as_posix():
        digest(p.read_bytes()) for p in environment.rglob('*') if p.is_file()},
        sort_keys=True).encode()
    answer = trial.parent / 'artifacts/out/answer.json'
    artifacts['answer.json'] = answer.read_bytes() if answer.exists() else b''
    data = {**report, 'artifacts': {k: digest(v) for k, v in artifacts.items()}}
    parent_path = root / 'results/integration/local-parser-8fc64684/preparation.json'
    parent = json.loads(parent_path.read_text())
    store = ReviewStore(Path(parent['store']))
    event = store.record_enforced_agent_replay(parent['review_id'],
        report=json.dumps(data).encode(), artifacts=artifacts)
    report['enforced_replay_evidence'] = event['data']
    report['decision'] = store.decide(parent['review_id'])
    (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (root / 'results/receipt-agent-enforced-latest.json').write_text(
        json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    result = finalize(Path(__file__).resolve().parents[1], args.folder.resolve())
    print(json.dumps(result['enforced_replay_evidence'], indent=2))
