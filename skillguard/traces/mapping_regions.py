"""Reconstruct bounded mapping ranges from existing Sysdig metadata, not page I/O.

Only observed, paired operations on known process-start identities contribute.
Missing arguments, remapping, forks/shared-VM ambiguity and overlapping calls
invalidate current range attribution. No collector, enforcer or completeness claim.
"""
from __future__ import annotations

import json
import re

from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.traces.native_calls import NativeCallPairs, native_file_path, native_thread_identity
from skillguard.traces.sysdig import parse_sysdig

KINDS = frozenset({'mmap', 'mmap2', 'mprotect', 'munmap'})
MODES = {'MAP_PRIVATE', 'MAP_SHARED', 'MAP_SHARED_VALIDATE'}
FLAGS = MODES | {'MAP_ANONYMOUS', 'MAP_ANON', 'MAP_FIXED', 'MAP_FIXED_NOREPLACE',
    'MAP_DENYWRITE', 'MAP_EXECUTABLE', 'MAP_FILE', 'MAP_NORESERVE', 'MAP_POPULATE',
    'MAP_NONBLOCK', 'MAP_LOCKED', 'MAP_STACK', 'MAP_32BIT'}
PROTECTIONS = {'PROT_READ', 'PROT_WRITE', 'PROT_EXEC', 'PROT_NONE', '0'}


def protection(value: object) -> set[str]:
    if not isinstance(value, str):
        raise ValueError('mapping protection absent')
    parts = set(value.split('|'))
    if (not parts <= PROTECTIONS or
            (parts & {'PROT_NONE', '0'} and len(parts) != 1)):
        raise ValueError('mapping protection unsupported')
    return parts


def bounds(address: object, length: object, page_size: int) -> tuple[int, int]:
    if type(address) is not int:
        if not isinstance(address, str) or not re.fullmatch(r'(?:0x)?[0-9A-Fa-f]+', address):
            raise ValueError('mapping address unresolved')
        address = int(address, 16)  # Native Sysdig address formatter is hexadecimal.
    if not isinstance(length, str) or not re.fullmatch(r'[0-9]+', length):
        raise ValueError('mapping length unresolved')
    size = int(length)
    end = address + ((size + page_size - 1) // page_size) * page_size
    if address < 0 or address % page_size or not size or end >= 2**64:
        raise ValueError('mapping range invalid')
    return address, end


def subtract(regions: list[dict], start: int, end: int) -> list[dict]:
    remainder = []
    for region in regions:
        if region['end'] <= start or region['start'] >= end:
            remainder.append(region)
            continue
        if region['start'] < start:
            remainder.append({**region, 'end': start})
        if region['end'] > end:
            remainder.append({**region, 'start': end})
    return remainder


def analyze_mapping_regions(text: str, *, container_id: str, page_size: int) -> dict:
    if (type(page_size) is not int or not 1024 <= page_size <= 65536
            or page_size & (page_size - 1)):
        raise ValueError('Native base page size must be supplied and valid')
    parse_sysdig(text, container_id=container_id)  # Existing binding and raw-result validation.
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    rows = [r for r in rows if r.get('container.full_id') == container_id
            and r.get('container.id') == container_id[:12]]
    if any(a['evt.num'] >= b['evt.num'] for a, b in zip(rows, rows[1:], strict=False)):
        raise ValueError('Native mapping events must retain chronological order')
    pairs = NativeCallPairs(KINDS, 0)
    spaces, races, changes, mappings, gaps = {}, set(), [], [], {}
    shared_unknown = set()
    seen_processes = set()
    unidentified_sharing = False
    private_after_unidentified = set()
    readable, writable = set(), set()

    def invalidate(row, detail):
        identity = native_thread_identity(row)
        if identity:
            spaces.pop(identity[:2], None)
        gaps[f"sysdig:{row['evt.num']}"] = detail

    def capabilities(region, prot):
        if region['path'] is not None:
            if 'PROT_READ' in prot:
                readable.add(region['path'])
            if 'PROT_WRITE' in prot and region['shared']:
                writable.add(region['path'])

    for row in rows:
        kind, direction = row['evt.type'], row['evt.dir']
        identity = native_thread_identity(row)
        if not identity:
            if kind in {'clone', 'clone3', 'fork', 'vfork'}:
                unidentified_sharing = True
                private_after_unidentified.clear()
                spaces.clear()
                invalidate(row, 'address-space sharing lacks process identity')
            if kind in KINDS | {'mremap', 'pkey_mprotect'}:
                # Cannot know which address space changed; clear all attribution.
                spaces.clear()
                invalidate(row, 'mapping process-start/thread identity unresolved')
            continue
        process = identity[:2]
        parent = (row.get('proc.ppid'), row.get('proc.ppid.ts'))
        if process not in seen_processes and parent in shared_unknown:
            shared_unknown.add(process)
        seen_processes.add(process)
        if kind in {'execve', 'execveat'} and direction == '<' and row['evt.rawres'] == 0:
            spaces.pop(process, None)
            shared_unknown.discard(process)  # Successful exec creates a private address space.
            private_after_unidentified.add(process)
        if kind == 'procexit' and row.get('thread.tid') == row.get('proc.pid'):
            spaces.pop(process, None)
        if kind in {'mremap', 'pkey_mprotect', 'clone', 'clone3', 'fork', 'vfork'}:
            if kind in {'clone', 'clone3', 'fork', 'vfork'}:
                shared_unknown.add(process)
            invalidate(row, 'address-space mutation/sharing arguments not reconstructed')
            continue
        if kind not in KINDS:
            pairs.consume(row)
            continue
        if direction == '>' and any(key[:2] == process for key in pairs.pending):
            races.add(process)
            invalidate(row, 'overlapping native mapping calls; order ambiguous')
        entry = pairs.consume(row)
        if direction == '>':
            continue
        if process in races:
            invalidate(row, 'overlapping native mapping completion; attribution invalidated')
            if not any(key[:2] == process for key in pairs.pending):
                races.discard(process)
            continue
        if row['evt.rawres'] < 0:
            invalidate(row, 'failed mapping call; partial side effects not inferred')
            continue
        if entry is None:
            invalidate(row, 'mapping entry missing or ambiguous')
            continue
        if (process in shared_unknown
                or unidentified_sharing and process not in private_after_unidentified):
            invalidate(row, 'address-space sharing unresolved until observed successful exec')
            continue
        try:
            start, end = bounds(row['evt.rawres'] if kind in {'mmap', 'mmap2'} else
                                entry.get('evt.arg.addr'), entry.get('evt.arg.length'), page_size)
            current = spaces.get(process, [])
            if kind in {'mmap', 'mmap2'}:
                prot = protection(entry.get('evt.arg.prot'))
                flags = set((entry.get('evt.arg.flags') or '').split('|'))
                if not flags <= FLAGS or len(flags & MODES) != 1:
                    raise ValueError('mapping mode/flags unsupported')
                anonymous = bool(flags & {'MAP_ANONYMOUS', 'MAP_ANON'})
                path = None if anonymous else native_file_path(entry.get('evt.arg.fd'))
                if path is None and not anonymous:
                    raise ValueError('mapping backing file unresolved')
                overlap = any(r['start'] < end and r['end'] > start for r in current)
                if overlap and 'MAP_FIXED' not in flags:
                    raise ValueError('mapping overlaps without observed fixed replacement')
                region = {'start': start, 'end': end, 'path': path, 'anonymous': anonymous,
                    'shared': bool(flags & {'MAP_SHARED', 'MAP_SHARED_VALIDATE'}),
                    'protection': entry['evt.arg.prot'], 'mapping_ref': f"sysdig:{row['evt.num']}"}
                spaces[process] = sorted(subtract(current, start, end) + [region],
                                         key=lambda r: r['start'])
                mappings.append({**region, 'process_identity': list(process)})
                capabilities(region, prot)
                continue
            overlap = sorted(({**r, 'start': max(start, r['start']), 'end': min(end, r['end'])}
                for r in current if r['start'] < end and r['end'] > start),
                key=lambda r: r['start'])
            cursor = start
            for region in overlap:
                if region['start'] != cursor:
                    raise ValueError('mapping change spans an unobserved range')
                cursor = region['end']
            if cursor != end:
                raise ValueError('mapping change backing range unobserved')
            remaining = subtract(current, start, end)
            if kind == 'mprotect':
                prot = protection(entry.get('evt.arg.prot'))
                for region in overlap:
                    capabilities(region, prot)
                remaining += [{**r, 'protection': entry['evt.arg.prot']} for r in overlap]
            spaces[process] = sorted(remaining, key=lambda r: r['start'])
            changes.append({'kind': kind, 'start': start, 'end': end,
                'protection': entry.get('evt.arg.prot'), 'backing_ranges': overlap,
                'entry_ref': f"sysdig:{entry['evt.num']}", 'exit_ref': f"sysdig:{row['evt.num']}",
                'process_identity': list(process), 'page_access_observed': False})
        except ValueError as error:
            invalidate(row, str(error))
    pairs.finish()
    return {'page_size': page_size, 'mappings': mappings, 'changes': changes,
        'unresolved_events': gaps | pairs.gaps,
        'mapping_capabilities': BehavioralEnvelope(files_read=readable,
            files_written=writable).to_dict(), 'complete': False, 'activation_permitted': False,
        'scope': 'Observed native mapping ranges only; no byte access or inode identity proof'}
