"""Validate fixed file-object controls against existing native trace metadata."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillguard.review.snapshot import digest
from skillguard.traces.file_identity import analyze_file_identity
from skillguard.traces.file_identity_controls import verify_controls


def analyze(folder: Path) -> dict:
    backend = json.loads((folder / 'backend.json').read_text())
    if (backend.get('fixed_probe_passed') is not True or backend.get('runner_stopped') is not True
            or backend.get('error') or backend.get('sysdig_version') != 'sysdig version 0.41.4'):
        raise ValueError('Healthy pinned native capture required')
    artifacts = {name: (folder / name).read_bytes()
                 for name in ('workload.jsonl', 'probe-console.json')}
    if any(digest(raw) != backend['artifacts'][name] for name, raw in artifacts.items()):
        raise ValueError('Native file identity source changed')
    checks = json.loads(artifacts['probe-console.json'])['workload_checks']['file_identity_checks']
    controls = verify_controls(artifacts['workload.jsonl'].decode(),
                              container_id=backend['container_id'], checks=checks)
    return {'source_run': backend['run_id'], 'controls': controls,
        'analysis': analyze_file_identity(artifacts['workload.jsonl'].decode(),
                                         container_id=backend['container_id']),
        'artifacts': {name: digest(raw) for name, raw in artifacts.items()},
        'complete': False, 'activation_permitted': False, 'model_calls': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.folder)
    (args.folder / 'file-identity-controls.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
