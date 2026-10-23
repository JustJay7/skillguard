"""Check fake IPC byte counts against the existing paired native trace."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillguard.review.snapshot import digest
from skillguard.traces.native_calls import NativeCallPairs, native_thread_identity
from skillguard.traces.sysdig import parse_sysdig

CONTROLS = (
    ('sendmsg', 'unix', 'unix_sent', 'unix_fds', 0, 17),
    ('recvmsg', 'unix', 'unix_received', 'unix_fds', 1, 17),
    ('write', 'unix', 'unix_written', 'unix_fds', 0, 15),
    ('read', 'unix', 'unix_read', 'unix_fds', 1, 15),
    ('writev', 'pipe', 'pipe_written', 'pipe_fds', 1, 15),
    ('readv', 'pipe', 'pipe_read', 'pipe_fds', 0, 15),
)


def verify_controls(text: str, *, container_id: str, checks: dict) -> dict:
    evidence = parse_sysdig(text, container_id=container_id)
    for name in ('unix_fds', 'pipe_fds'):
        fds = checks.get(name)
        if (not isinstance(fds, list) or len(fds) != 2 or fds[0] == fds[1]
                or any(type(v) is not int or v < 0 for v in fds)):
            raise ValueError('Distinct fixed IPC descriptors required')
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    rows = [r for r in rows if r.get('container.full_id') == container_id]
    selected, identity = [], None
    for kind, fd_type, count, fds, index, expected in CONTROLS:
        if type(checks.get(count)) is not int or checks[count] != expected:
            raise ValueError('Independent fixed IPC byte count differs')
        matches = [r for r in rows if r['evt.type'] == kind and r['evt.dir'] == '<'
            and r.get('fd.type') == fd_type and r.get('fd.num') == checks[fds][index]
            and r.get('evt.rawres') == expected
            and r.get('proc.exepath') == '/usr/local/bin/python3.12'
            and r.get('proc.args[0]') == '-c']
        if len(matches) != 1 or native_thread_identity(matches[0]) is None:
            raise ValueError('Fixed IPC event is missing or ambiguous')
        current = native_thread_identity(matches[0])
        if identity is not None and current != identity:
            raise ValueError('Fixed IPC controls require one observed process/thread')
        identity = current
        selected.append(matches[0])
    pairs = NativeCallPairs(frozenset(r['evt.type'] for r in selected), 1)
    entries = {}
    for row in rows:
        if native_thread_identity(row) == identity:
            entry = pairs.consume(row)
            if entry is not None:
                entries[row['evt.num']] = entry
    verified = []
    for row in selected:
        entry = entries.get(row['evt.num'])
        if (entry is None or entry.get('fd.num') != row['fd.num']
                or entry.get('fd.type') != row['fd.type']):
            raise ValueError('Fixed IPC completion lacks a matching native descriptor entry')
        ref = f"sysdig:{row['evt.num']}"
        records = [r for r in evidence.socket_io if r['exit_ref'] == ref]
        if (len(records) != 1 or records[0]['bytes_transferred'] != row['evt.rawres']
                or records[0]['peer_endpoint'] is not None
                or ref not in evidence.unresolved_events):
            raise ValueError('IPC byte records must preserve unresolved peer/lifetime evidence')
        verified.append(records[0] | {'entry_ref': f"sysdig:{entry['evt.num']}"})
    # This native environment did not complete the unconnected localhost UDP send.
    # Retain the failed attempt, never treat missing tuple data as no network use.
    err = checks.get('udp_errno')
    if type(err) is not int or err <= 0 or 'udp_sent' in checks:
        raise ValueError('Expected unsuccessful fixed UDP control; new outcome needs validation')
    udp = [r for r in rows if native_thread_identity(r) == identity
        and r['evt.type'] == 'sendto' and r['evt.dir'] == '<'
        and r.get('evt.rawres') == -err]
    if len(udp) != 1 or f"sysdig:{udp[0]['evt.num']}" not in evidence.unresolved_events:
        raise ValueError('Unresolved UDP attempt must remain an explicit gap')
    return {'fixed_ipc_controls_passed': True, 'controls': verified,
        'udp_completed': False, 'udp_errno': err,
        'udp_reference': f"sysdig:{udp[0]['evt.num']}",
        'udp_destination_observed': False, 'tcp_peer_controls_passed': False,
        'complete': False, 'activation_permitted': False, 'model_calls': 0,
        'scope': 'Six fake IPC byte transfers; no socket/pipe lifetime, '
                 'ancillary-data or network delivery proof'}


def analyze(folder: Path) -> dict:
    backend = json.loads((folder / 'backend.json').read_text())
    if (backend.get('fixed_probe_passed') is not True
            or backend.get('runner_stopped') is not True or backend.get('error')
            or backend.get('sysdig_version') != 'sysdig version 0.41.4'):
        raise ValueError('Healthy pinned native capture required')
    artifacts = {name: (folder / name).read_bytes()
                 for name in ('workload.jsonl', 'probe-console.json')}
    if any(digest(raw) != backend['artifacts'][name] for name, raw in artifacts.items()):
        raise ValueError('Native socket control source changed')
    checks = json.loads(artifacts['probe-console.json'])['workload_checks']['socket_ipc_checks']
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
    (args.folder / 'socket-controls.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
