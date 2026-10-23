from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.finalize_recorded_agent_replay import finalize as finalize_replay
from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore


def finalize(root: Path, folder: Path) -> dict:
    report = finalize_replay(root, folder)
    native = folder / 'native-job'
    trial = Path(report['native_trial'])
    artifacts = {name: (native / 'capture' / name).read_bytes()
                 for name in ('capture.json', 'events.jsonl', 'events.scap.gz', 'stats.txt')}
    artifacts.update({'container.json': (native / 'container-inspect.json').read_bytes(),
        'trial.json': trial.read_bytes(),
        'trajectory.json': (trial.parent / 'agent/trajectory.json').read_bytes()})
    data = {**report, 'artifacts': {k: digest(v) for k, v in artifacts.items()}}
    tasks = json.loads((root / 'results/receipt-agent-tasks-latest.json').read_text())
    parent = json.loads(Path(tasks['preparation']).read_text())
    store = ReviewStore(Path(parent['store']))
    event = store.record_agent_capture(parent['review_id'], report=json.dumps(data).encode(),
                                     artifacts=artifacts)
    report['native_capture_evidence'] = event['data']
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
    print(json.dumps(result['native_capture_evidence'], indent=2))
