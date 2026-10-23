import json
from pathlib import Path

import pytest

from skillguard.traces.mapping_regions import analyze_mapping_regions
from tests.test_process_scope import CONTAINER, row


def call(number, kind='mmap', *, address='0', length='12288', result=8192,
         path='/fake/one', prot='PROT_READ', flags='MAP_SHARED', tid=20, pid=20, ts=200):
    entry = row(number, pid, ts, kind) | {'evt.dir': '>', 'evt.rawres': None,
        'thread.tid': tid, 'evt.arg.addr': address, 'evt.arg.length': length,
        'evt.arg.fd': '<f>' + path, 'evt.arg.flags': flags, 'evt.arg.prot': prot}
    exit_row = row(number + 1, pid, ts, kind) | {'evt.rawres': result, 'thread.tid': tid}
    return [entry, exit_row]


def analyze(rows):
    return analyze_mapping_regions('\n'.join(json.dumps(r) for r in rows),
                                   container_id=CONTAINER, page_size=4096)


def test_shared_permission_upgrade_has_backing_identity_without_byte_write_claim():
    result = analyze(call(1) + call(3, 'mprotect', address='2000', length='4096', result=0,
                                    prot='PROT_READ|PROT_WRITE'))
    assert result['changes'][0]['backing_ranges'][0]['path'] == '/fake/one'
    assert result['mapping_capabilities']['files_written'] == ['/fake/one']
    assert result['unresolved_events'] == {}
    assert result['complete'] is False and result['activation_permitted'] is False
    assert result['changes'][0]['page_access_observed'] is False


def test_private_permission_upgrade_never_claims_shared_file_write():
    result = analyze(call(1, flags='MAP_PRIVATE') + call(3, 'mprotect', address='2000',
        length='4096', result=0, prot='PROT_READ|PROT_WRITE'))
    assert result['mapping_capabilities']['files_written'] == []


def test_foreign_short_container_id_cannot_replace_a_bound_file_mapping():
    original = call(1)
    foreign = call(3, path='/foreign', flags='MAP_SHARED|MAP_FIXED')
    for value in foreign:
        value['container.id'] = 'foreign'
    upgrade = call(5, 'mprotect', address='2000', length='4096', result=0,
                   prot='PROT_READ|PROT_WRITE')
    assert analyze(original + foreign + upgrade) == analyze(original + upgrade)


def test_partial_unmap_splits_lifetime_and_hole_never_rebinds():
    result = analyze(call(1) + call(3, 'munmap', address='3000', length='4096', result=0)
        + call(5, 'mprotect', address='2000', length='4096', result=0)
        + call(7, 'mprotect', address='4000', length='4096', result=0)
        + call(9, 'mprotect', address='3000', length='4096', result=0))
    assert len(result['changes']) == 3
    assert 'unobserved' in result['unresolved_events']['sysdig:10']


def test_fixed_address_replacement_rebinds_to_new_file_and_anonymous_overwrites():
    result = analyze(call(1) + call(3, result=8192, path='/fake/two', flags='MAP_SHARED|MAP_FIXED')
        + call(5, 'mprotect', address='2000', length='4096', result=0)
        + call(7, result=8192, flags='MAP_PRIVATE|MAP_FIXED|MAP_ANONYMOUS')
        + call(9, 'mprotect', address='2000', length='4096', result=0))
    assert result['changes'][0]['backing_ranges'][0]['path'] == '/fake/two'
    assert result['changes'][1]['backing_ranges'][0]['path'] is None


def test_page_rounding_uses_supplied_native_size():
    result = analyze(call(1, length='1') + call(3, 'mprotect', address='2000',
                                             length='4096', result=0))
    assert result['mappings'][0]['end'] == 12288
    assert len(result['changes']) == 1


@pytest.mark.parametrize('kind', ['mremap', 'pkey_mprotect', 'clone', 'clone3', 'fork', 'vfork'])
def test_unreconstructed_address_space_mutation_invalidates_bindings(kind):
    result = analyze(call(1) + [row(3, 20, 200, kind)] +
        call(4, 'mprotect', address='2000', length='4096', result=0))
    assert result['changes'] == [] and result['unresolved_events']


def test_exec_and_pid_reuse_do_not_inherit_old_mapping():
    for boundary, ts in (([row(3, 20, 200, 'execve')], 200), ([], 201)):
        result = analyze(call(1) + boundary + call(4, 'mprotect', address='2000',
            length='4096', result=0, ts=ts))
        assert result['changes'] == []


def test_other_threads_use_same_address_space_but_racing_syscalls_invalidate():
    result = analyze(call(1) + call(3, 'mprotect', address='2000', length='4096',
                                    result=0, tid=21))
    assert len(result['changes']) == 1
    first, second = call(1), call(2, tid=21, result=32768)
    first[1]['evt.num'] = 3
    second[1]['evt.num'] = 4
    result = analyze([first[0], second[0], first[1], second[1]] +
        call(5, 'mprotect', address='2000', length='4096', result=0))
    assert result['changes'] == [] and result['mappings'] == []


@pytest.mark.parametrize('fault', ['length', 'address', 'prot', 'fd', 'huge', 'grow', 'identity'])
def test_unknown_native_arguments_cannot_produce_lifetime_identity(fault):
    rows = call(1)
    if fault == 'length':
        rows[0]['evt.arg.length'] = None
    elif fault == 'address':
        rows[1]['evt.rawres'] = 8193
    elif fault == 'prot':
        rows[0]['evt.arg.prot'] = 'PROT_GROWSDOWN'
    elif fault == 'fd':
        rows[0]['evt.arg.fd'] = '<UNKNOWN>'
    elif fault == 'huge':
        rows[0]['evt.arg.flags'] = 'MAP_SHARED|MAP_HUGETLB'
    elif fault == 'grow':
        rows[0]['evt.arg.flags'] = 'MAP_PRIVATE|MAP_GROWSDOWN'
    else:
        rows[1]['proc.pid.ts'] += 1
    result = analyze(rows + call(3, 'mprotect', address='2000', length='4096', result=0))
    assert result['changes'] == [] and result['unresolved_events']


def test_failed_protection_does_not_leave_false_known_state():
    result = analyze(call(1) + call(3, 'mprotect', address='2000', result=-12)
        + call(5, 'mprotect', address='2000', length='4096', result=0))
    assert result['changes'] == [] and result['unresolved_events']


def test_unknown_shared_vm_cannot_repopulate_attribution_before_exec():
    result = analyze(call(1) + [row(3, 20, 200, 'clone')] + call(4, result=32768)
        + call(6, 'mprotect', address='8000', length='4096', result=0))
    assert result['changes'] == []
    assert len(result['mappings']) == 1  # Historical pre-sharing mapping only.
    assert 'sharing unresolved' in result['unresolved_events']['sysdig:5']
    result = analyze(call(1) + [row(3, 20, 200, 'clone'), row(4, 20, 200, 'execve')]
        + call(5, result=32768)
        + call(7, 'mprotect', address='8000', length='4096', result=0))
    assert len(result['changes']) == 1


def test_exec_child_does_not_reinherit_parent_uncertainty_on_every_event():
    parent = [row(1, 20, 200, 'clone')]
    child = [row(2, 30, 300, 'execve')]
    child += call(3, pid=30, ts=300, tid=30) + call(5, 'mprotect', pid=30, ts=300,
        tid=30, address='2000', length='4096', result=0)
    for event in child:
        event.update({'proc.ppid': 20, 'proc.ppid.ts': 200})
    result = analyze(parent + child)
    assert len(result['changes']) == 1 and len(result['mappings']) == 1


def test_unidentified_clone_cannot_leave_or_repopulate_trusted_ranges():
    clone = row(3, 20, 200, 'clone')
    clone['proc.pid.ts'] = None
    result = analyze(call(1) + [clone] + call(4, result=32768)
        + call(6, 'mprotect', address='8000', length='4096', result=0))
    assert len(result['mappings']) == 1 and result['changes'] == []
    result = analyze(call(1) + [clone, row(4, 20, 200, 'execve')]
        + call(5, result=32768)
        + call(7, 'mprotect', address='8000', length='4096', result=0))
    assert len(result['changes']) == 1


def test_actual_native_mapping_fixture_resolves_upgrade_then_removal():
    folder = Path(__file__).parent / 'fixtures'
    source = json.loads((folder / 'sysdig-native-mapping-changes-source.json').read_text())
    result = analyze_mapping_regions((folder / 'sysdig-native-mapping-changes.jsonl').read_text(),
                                    container_id=source['container_id'], page_size=4096)
    assert [c['kind'] for c in result['changes']] == ['mprotect', 'munmap']
    assert all(c['backing_ranges'][0]['path'].endswith('/mapped-upgrade.txt')
               for c in result['changes'])
    assert result['mapping_capabilities']['files_written'] == [
        '/sandbox/fixed-trace-probe/mapped-upgrade.txt']
    assert set(result['unresolved_events']) == {'sysdig:343726'}
