"""Bounded positive observations of guide/resource/input/output I/O after inference."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from skillguard.evaluation.agent_task_protocol import (
    GUIDE_PATH,
    INPUT_PATH,
    OUTPUT_PATH,
    PARSER_PATH,
)
from skillguard.review.snapshot import digest


def verify_skill_use(report: dict, artifacts: dict[str, bytes]) -> dict:
    files = {'SKILL.md': digest(artifacts['guide.md']),
             'scripts/parse_receipt.py': digest(artifacts['parser.py'])}
    if digest(json.dumps(files, sort_keys=True).encode()) != report['candidate_sha256']:
        raise ValueError('Native collected skill bytes differ from the selected candidate')
    materialized = json.loads(artifacts['input-proof.json'])
    if (materialized.get('sha256') != digest(artifacts['receipt.txt'])
            or materialized.get('bytes') != len(artifacts['receipt.txt'])):
        raise ValueError('Native input materialization differs from collected receipt')
    rows = json.loads(artifacts['cost-rows.json'])
    first = datetime.fromisoformat(rows[0]['time_utc'])
    if first.tzinfo is None:
        raise ValueError('Native inference time requires an explicit timezone')
    earliest = int(first.timestamp()) * 1_000_000_000 + first.microsecond * 1000
    steps = json.loads(artifacts['trajectory.json'])['steps']
    last = datetime.fromisoformat([s for s in steps if s.get('source') == 'agent'][-1][
        'timestamp'])
    if last.tzinfo is None or last <= first:
        raise ValueError('Native agent execution window is invalid')
    latest = int(last.timestamp()) * 1_000_000_000 + last.microsecond * 1000
    cid = json.loads(artifacts['container.json'])['Id']
    reads = {GUIDE_PATH: [], PARSER_PATH: [], INPUT_PATH: []}
    writes = []
    for line in artifacts['events.jsonl'].decode().splitlines():
        event = json.loads(line)
        if (event.get('container.full_id') != cid or event.get('container.id') != cid[:12]):
            raise ValueError('Foreign receipt artifact event')
        if (type(event.get('evt.rawtime')) is not int
                or not earliest <= event['evt.rawtime'] <= latest
                or event.get('evt.dir') != '<' or type(event.get('evt.rawres')) is not int
                or event['evt.rawres'] <= 0):
            continue
        path, kind = event.get('fd.name'), event.get('evt.type')
        if kind in {'read', 'pread', 'readv', 'preadv', 'preadv2'} and path in reads:
            reads[path].append(event)
        elif kind in {'write', 'pwrite', 'writev', 'pwritev', 'pwritev2'} and path == OUTPUT_PATH:
            writes.append(event)

    def process(event):
        pid, start = event.get('proc.pid'), event.get('proc.pid.ts')
        if type(pid) is int and pid > 0 and type(start) is int and start > 0:
            return pid, start
        return None

    parser_processes = {process(e) for e in reads[PARSER_PATH] if process(e)
        and Path(e.get('proc.exepath') or '').name in {'python', 'python3', 'python3.12'}}
    used_input = [e for e in reads[INPUT_PATH] if process(e) in parser_processes]

    def refs(events):
        return ['sysdig:' + str(e['evt.num']) for e in events]

    from skillguard.evaluation.selected_skill_evidence import observed

    ordering = observed(artifacts['events.jsonl'], earliest, latest, include_refresh=True)
    return {**ordering, 'input_materialized_verified': True, 'selected_skill_bytes_verified': True,
        'guide_read_observed': bool(reads[GUIDE_PATH]),
        'receipt_read_observed': bool(reads[INPUT_PATH]),
        'parser_input_io_observed': bool(parser_processes and used_input),
        'answer_write_observed': bool(writes),
        'guide_read_references': refs(reads[GUIDE_PATH]),
        'parser_read_references': refs(reads[PARSER_PATH]),
        'parser_input_references': refs(used_input), 'answer_write_references': refs(writes),
        'scope': 'Positive reported artifact I/O during inference execution. Native discovery '
                 'and post-agent artifact collection are excluded. No causal learning or '
                 'completeness claim'}
