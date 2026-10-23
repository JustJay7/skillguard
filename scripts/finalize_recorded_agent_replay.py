from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillguard.evaluation.receipt_answer_grader import grade_answer
from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore


def finalize(root: Path, folder: Path) -> dict:
    report = json.loads((folder / 'report.json').read_text())
    native = folder / 'native-job'
    trial_path = Path(report['native_trial'])
    trial = json.loads(trial_path.read_text())
    task = folder / 'task'
    answer_path = trial_path.parent / 'artifacts/out/answer.json'
    answer = answer_path.read_text() if answer_path.exists() else None
    contract = json.loads((task / 'tests/contract.json').read_text())
    score = grade_answer(answer, contract)
    if trial['verifier_result']['rewards']['overall'] != score['overall']:
        raise ValueError('Native recorded domain grade differs')
    artifacts = {'trial.json': trial_path.read_bytes(),
        'trajectory.json': (trial_path.parent / 'agent/trajectory.json').read_bytes(),
        'parser.py': (trial_path.parent / 'artifacts/parse_receipt.py').read_bytes(),
        'manifest.json': (native / 'recorded/manifest.json').read_bytes(),
        'responses.json': json.dumps({p.name: p.read_text()
            for p in (native / 'recorded').glob('*.json') if p.name != 'manifest.json'}).encode()}
    report.pop('error', None)
    report.pop('error_type', None)
    report.update(completed_domain_cases=1, recomputed_grade=score,
                  artifacts={k: digest(v) for k, v in artifacts.items()})
    parent = json.loads((root / 'results/integration/local-parser-8fc64684/preparation.json')
                        .read_text())
    store = ReviewStore(Path(parent['store']))
    event = store.record_recorded_agent_replay(parent['review_id'],
        report=json.dumps(report).encode(), artifacts=artifacts)
    report['recorded_replay_evidence'] = event['data']
    report['decision'] = store.decide(parent['review_id'])
    (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    (root / 'results/receipt-agent-recorded-latest.json').write_text(
        json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    result = finalize(Path(__file__).resolve().parents[1], args.folder.resolve())
    print(json.dumps({k: result[k] for k in ('run_id', 'mode', 'model_requests',
        'native_agent_steps', 'completed_domain_cases', 'recomputed_grade', 'decision')}, indent=2))
