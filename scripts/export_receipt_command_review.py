"""Export unreviewed issued actions as data; never execute or classify their text."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillguard.evaluation.receipt_command_audit import actions
from skillguard.review.snapshot import digest


def pending(root: Path, experiment: Path) -> list[dict]:
    experiment = experiment.resolve()
    if not experiment.is_relative_to(root / 'results/integration'):
        raise ValueError('Local experiment required')
    folder = experiment.parent
    parts = folder / 'command-review-parts'
    parts.mkdir(exist_ok=True)
    exported = []
    for result in json.loads(experiment.read_text())['results']:
        if not result.get('verified') or (parts / (result['trial_id'] + '.json')).exists():
            continue
        raw = (Path(result['native_trial']).parent / 'agent/trajectory.json').read_bytes()
        row = {'trial_id': result['trial_id'], 'trajectory_sha256': digest(raw),
            'actions': actions(raw), 'reviewed': False, 'review_reason': '',
            'unsafe_tool_call_ids': []}
        target = folder / (result['trial_id'] + '-command-review-template.json')
        target.write_text(json.dumps(row, indent=2) + '\n')
        exported.append(row)
    return exported


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(pending(Path(__file__).resolve().parents[1], args.experiment), indent=2))
