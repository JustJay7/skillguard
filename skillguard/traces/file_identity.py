"""Report native file-object metadata matches without resolving path permissions."""
from __future__ import annotations

import json
from collections import defaultdict

from skillguard.traces.file_mutations import OPENS, native_path
from skillguard.traces.native_calls import native_thread_identity
from skillguard.traces.socket_io import READ_KINDS, WRITE_KINDS


def native_object_identity(row: dict) -> dict | None:
    values = [row.get(k) for k in ('fd.dev.major', 'fd.dev.minor', 'fd.ino')]
    if (any(type(v) is not int for v in values)
            or not all(0 <= v < 2**32 for v in values[:2])
            or not 0 < values[2] < 2**64):
        return None
    return dict(zip(('device_major', 'device_minor', 'inode'), values, strict=True))


def analyze_file_identity(text: str, *, container_id: str) -> dict:
    from skillguard.traces.sysdig import parse_sysdig

    parse_sysdig(text, container_id=container_id)  # exact binding, results and duplicates
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    rows.sort(key=lambda r: r.get('evt.num', 0))
    observations, changes, gaps = [], [], {}
    groups, previous = defaultdict(list), {}
    for row in rows:
        kind = row.get('evt.type')
        if (row.get('container.full_id') != container_id
                or row.get('container.id') != container_id[:12] or row.get('evt.dir') != '<'
                or row.get('fd.type') != 'file' or kind not in OPENS | READ_KINDS | WRITE_KINDS):
            continue
        count = row.get('evt.rawres')
        if type(count) is not int:
            raise ValueError('Missing or invalid native file identity outcome')
        if count < 0 or count == 0 and kind not in OPENS:
            continue
        ref = f"sysdig:{row['evt.num']}"
        process, fd = native_thread_identity(row), row.get('fd.num')
        obj, path = native_object_identity(row), native_path(row.get('fd.name'))
        if (process is None or type(fd) is not int or fd < 0 or obj is None or path is None
                or kind in OPENS and count != fd):
            gaps[ref] = 'native file object/process/descriptor/path identity unresolved'
            continue
        record = {'kind': kind, 'process_identity': list(process[:2]),
            'thread_id': process[2], 'fd': fd, 'reported_path': path,
            'object_identity': obj, 'exit_ref': ref,
            'content_io_observed': kind not in OPENS,
            'bytes_transferred': count if kind not in OPENS else None,
            'complete': False}
        observations.append(record)
        key = tuple(process[:2]) + (fd,)
        before = previous.get(key)
        if before and before['object_identity'] != obj:
            changes.append({'process_identity': list(process[:2]), 'fd': fd,
                'before': before['object_identity'], 'after': obj,
                'before_ref': before['exit_ref'], 'after_ref': ref,
                'reuse_or_change_verified': False})
        previous[key] = record
        groups[tuple(process[:2]) + tuple(obj.values())].append(record)
        gaps[ref] = ('native object observation; mount/inode generation, FD sharing/lifetime '
                     'and current path binding unverified')
    matches = []
    for key, records in sorted(groups.items()):
        paths = sorted({r['reported_path'] for r in records})
        if len(paths) > 1:
            matches.append({'process_identity': list(key[:2]),
                'object_identity': records[0]['object_identity'], 'reported_paths': paths,
                'event_refs': [r['exit_ref'] for r in records],
                'alias_verified': False, 'generation_verified': False})
    return {'observations': observations, 'reported_identity_matches': matches,
        'reported_descriptor_identity_changes': changes, 'unresolved_events': gaps,
        'complete': False, 'activation_permitted': False,
        'path_permissions_canonicalized': False,
        'scope': 'Native reported device/inode/FD observations; '
                 'no current path, alias or lifetime proof'}
