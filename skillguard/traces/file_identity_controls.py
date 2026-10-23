"""Cross-check known fake file controls against supplied native event metadata."""
from __future__ import annotations

import json

from skillguard.traces.file_identity import analyze_file_identity, native_object_identity
from skillguard.traces.native_calls import NativeCallPairs, native_thread_identity

PHASES = ('original_open', 'original_after_rename', 'hardlink_read', 'replacement_read',
          'original_after_replacement', 'reused_descriptor_read')


def verify_controls(text: str, *, container_id: str, checks: dict) -> dict:
    paths = {key: '/sandbox/fixed-trace-probe/identity-' + name + '.txt'
             for key, name in (('source', 'source'), ('alias', 'hardlink'),
                               ('renamed', 'renamed'), ('reused', 'reused'))}
    if checks.get('paths') != paths or set(checks.get('observations', {})) != set(PHASES):
        raise ValueError('Exact known file identity controls required')
    control = checks['observations']
    objects = {}
    for phase in PHASES:
        c = control[phase]
        obj = native_object_identity({'fd.dev.major': c.get('device_major'),
            'fd.dev.minor': c.get('device_minor'), 'fd.ino': c.get('inode')})
        expected = 25 if phase == 'replacement_read' else 22
        if (obj is None or type(c.get('fd')) is not int or c['fd'] < 0
                or phase != 'original_open' and (c.get('content_correct') is not True
                    or type(c.get('bytes_read')) is not int or c['bytes_read'] != expected)):
            raise ValueError('Independent live-handle identity/count check differs')
        objects[phase] = obj
    original = objects['original_open']
    if (any(objects[phase] != original for phase in (
            'original_after_rename', 'hardlink_read', 'original_after_replacement'))
            or objects['replacement_read'] == original
            or objects['reused_descriptor_read'] in (original, objects['replacement_read'])
            or any(control[phase]['fd'] != control['original_open']['fd'] for phase in (
                'original_after_rename', 'original_after_replacement', 'reused_descriptor_read'))
            or control['hardlink_read']['fd'] == control['original_open']['fd']):
        raise ValueError('Hardlink, replacement or descriptor reuse control differs')
    analysis = analyze_file_identity(text, container_id=container_id)
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    rows = sorted((r for r in rows if r.get('container.full_id') == container_id
                   and r.get('container.id') == container_id[:12]),
                  key=lambda r: r['evt.num'])
    selected, last, identity = [], 0, None
    for phase, path_key in zip(PHASES, ('source', 'source', 'alias', 'renamed', 'source', 'reused'),
                               strict=True):
        kind = 'openat' if phase == 'original_open' else 'read'
        matches = [r for r in rows if r['evt.type'] == kind and r['evt.dir'] == '<'
            and r['evt.num'] > last and r.get('fd.name') == paths[path_key]
            and r.get('fd.num') == control[phase]['fd']
            and native_object_identity(r) == objects[phase]
            and r.get('evt.rawres') == (control[phase]['fd'] if kind == 'openat'
                                       else control[phase]['bytes_read'])
            and (kind != 'openat' or 'O_RDONLY' in str(r.get('evt.arg.flags')).split('|'))]
        expected_matches = 2 if phase == 'original_after_rename' else 1
        if len(matches) != expected_matches:
            raise ValueError('Fixed live-handle observation lacks native corroboration')
        # The same old handle is deliberately read twice; bind each phase in order.
        r = matches[0]
        current = native_thread_identity(r)
        if current is None or identity is not None and identity != current:
            raise ValueError('Fixed file identity controls require one native process/thread')
        identity, last = current, r['evt.num']
        selected.append(r)
    pairs, entries = NativeCallPairs(frozenset({'openat', 'read'}), 0), {}
    for r in rows:
        if native_thread_identity(r) == identity:
            entry = pairs.consume(r)
            if entry:
                entries[r['evt.num']] = entry
    for r in selected:
        entry = entries.get(r['evt.num'])
        if (entry is None or r['evt.type'] == 'read' and (
                entry.get('fd.num') != r['fd.num']
                or native_object_identity(entry) != native_object_identity(r))):
            raise ValueError('File identity completion lacks a matching native entry')
    scope = [r for r in rows if native_thread_identity(r) == identity and r['evt.dir'] == '<']
    def unique(kind: str, predicate) -> dict:
        matches = [r for r in scope if r['evt.type'] == kind and r.get('evt.rawres') == 0
                   and predicate(r)]
        if len(matches) != 1:
            raise ValueError('Fixed file namespace/lifetime event missing or ambiguous')
        return matches[0]
    link = unique('linkat', lambda r: {r.get('fs.path.source'), r.get('fs.path.target')}
                  == {paths['source'], paths['alias']})
    rename = unique('renameat', lambda r: (r.get('fs.path.source'), r.get('fs.path.target'))
                    == (paths['source'], paths['renamed']))
    unlink = unique('unlinkat', lambda r: r.get('fs.path.name') == paths['renamed'])
    close = unique('close', lambda r: r.get('fd.num') == control['original_open']['fd']
        and native_object_identity(r) == original and r['evt.num'] > selected[4]['evt.num'])
    sequence = [selected[0], link, rename, selected[1], selected[2], unlink,
                selected[3], selected[4], close, selected[5]]
    if any(a['evt.num'] >= b['evt.num'] for a, b in zip(sequence, sequence[1:], strict=False)):
        raise ValueError('Fixed rename/replacement/reuse order differs')
    references = [f"sysdig:{r['evt.num']}" for r in selected]
    observed = {r['exit_ref']: r for r in analysis['observations']}
    if any(ref not in observed or ref not in analysis['unresolved_events'] for ref in references):
        raise ValueError('Identity observations must retain general path/lifetime uncertainty')
    return {'fixed_controls_passed': True,
        'controls': {phase: observed[ref] | {
                         'entry_ref': f"sysdig:{entries[r['evt.num']]['evt.num']}"}
                     for phase, ref, r in zip(PHASES, references, selected, strict=True)},
        'namespace_refs': {name: f"sysdig:{r['evt.num']}" for name, r in (
            ('link', link), ('rename', rename), ('unlink', unlink), ('close_original', close))},
        'stale_reported_path_observed': True, 'same_object_hardlink_control_passed': True,
        'replacement_object_control_passed': True, 'descriptor_reuse_control_passed': True,
        'complete': False, 'activation_permitted': False, 'model_calls': 0,
        'scope': 'Six known live-handle checks; no general path alias or inode generation proof'}
