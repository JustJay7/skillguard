"""Validate fixed directory/TMPFILE controls against existing native capture."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillguard.review.snapshot import digest
from skillguard.traces.sysdig import parse_sysdig


def verify_controls(text: str, *, container_id: str, checks: dict) -> dict:
    if (checks.get('directory_is_directory') is not True
            or checks.get('directory_access_mode') != 0
            or checks.get('tmpfile_supported') is not True
            or checks.get('tmpfile_is_regular') is not True
            or checks.get('tmpfile_link_count') != 0):
        raise ValueError('Both independent positive directory/TMPFILE controls are required')
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    rows = [r for r in rows if r.get('container.full_id') == container_id
        and r.get('evt.type') == 'openat' and r.get('evt.dir') == '<'
        and r.get('fd.name') == checks['directory_path']]
    if len(rows) != 2:
        raise ValueError('Native directory control event identity is ambiguous')
    directory, temporary = rows
    flags = [set(r['evt.arg.flags'].split('|')) for r in rows]
    if (not {'O_RDONLY', 'O_DIRECTORY', 'O_TMPFILE'} <= flags[0]
            or not {'O_RDWR', 'O_DIRECTORY', 'O_TMPFILE'} <= flags[1]
            or directory['evt.rawres'] != checks['directory_fd']
            or temporary['evt.rawres'] != checks['tmpfile_fd']
            or (directory['proc.pid'], directory['proc.pid.ts']) !=
                (temporary['proc.pid'], temporary['proc.pid.ts'])):
        raise ValueError('Native control flags, descriptors or process identity differ')
    parsed = parse_sysdig(text, container_id=container_id)
    read_ref, write_ref = [f"sysdig:{r['evt.num']}" for r in rows]
    observed = [r for r in parsed.directory_opens if r['exit_ref'] == read_ref]
    if (len(observed) != 1 or read_ref in parsed.unresolved_events
            or parsed.unresolved_events.get(write_ref) !=
                'openat unnamed temporary inode not represented'):
        raise ValueError('Readonly directory resolution must preserve true TMPFILE gap')
    return {'fixed_controls_passed': True, 'directory_reference': read_ref,
        'unnamed_file_reference': write_ref, 'directory_open': observed[0],
        'native_unnamed_file_reported_type': temporary.get('fd.type'),
        'unnamed_file_actual_control_type': 'regular',
        'complete': False, 'activation_permitted': False, 'model_calls': 0,
        'scope': 'Bounded fixed controls; no inode lifetime or byte-access completeness proof'}


def analyze(folder: Path) -> dict:
    backend = json.loads((folder / 'backend.json').read_text())
    if (backend.get('fixed_probe_passed') is not True
            or backend.get('runner_stopped') is not True or backend.get('error')
            or backend.get('sysdig_version') != 'sysdig version 0.41.4'):
        raise ValueError('Healthy pinned native capture required')
    artifacts = {name: (folder / name).read_bytes()
                 for name in ('workload.jsonl', 'probe-console.json')}
    if any(digest(raw) != backend['artifacts'][name] for name, raw in artifacts.items()):
        raise ValueError('Native directory control source changed')
    checks = json.loads(artifacts['probe-console.json'])['workload_checks']['directory_open_checks']
    report = verify_controls(artifacts['workload.jsonl'].decode(),
                             container_id=backend['container_id'], checks=checks)
    report.update(source_run=backend['run_id'],
        artifacts={name: digest(raw) for name, raw in artifacts.items()})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.folder)
    (args.folder / 'directory-controls.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
