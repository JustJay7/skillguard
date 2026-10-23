import json

import pytest

from skillguard.traces.file_identity import analyze_file_identity
from tests.test_process_scope import CONTAINER, row


def event(number=1, *, path='/fake/original', inode=77, fd=3, start=300):
    value = row(number, 30, start, path=path)
    value.update({'fd.num': fd, 'fd.dev.major': 0, 'fd.dev.minor': 42, 'fd.ino': inode})
    return value


def analyze(*values):
    return analyze_file_identity('\n'.join(json.dumps(r) for r in values),
                                 container_id=CONTAINER)


def test_same_reported_object_under_two_paths_never_canonicalizes_permissions():
    result = analyze(event(), event(2, path='/fake/hardlink', fd=4))
    assert len(result['observations']) == 2
    match = result['reported_identity_matches'][0]
    assert match['reported_paths'] == ['/fake/hardlink', '/fake/original']
    assert match['object_identity'] == {'device_major': 0, 'device_minor': 42, 'inode': 77}
    assert match['alias_verified'] is False
    assert match['generation_verified'] is False
    assert result['complete'] is False and result['activation_permitted'] is False
    assert result['path_permissions_canonicalized'] is False
    assert result['unresolved_events']  # FD generation/mount/races remain gaps


def test_same_path_and_reused_descriptor_do_not_hide_replacement_object():
    result = analyze(event(), event(2, inode=88))
    change = result['reported_descriptor_identity_changes'][0]
    assert change['before']['inode'] == 77
    assert change['after']['inode'] == 88
    assert change['fd'] == 3
    assert change['reuse_or_change_verified'] is False
    assert result['reported_identity_matches'] == []


def test_pid_reuse_and_device_changes_do_not_merge_reported_objects():
    old, new = event(), event(2, path='/other', start=400)
    other_device = event(3, path='/dev', fd=4)
    other_device['fd.dev.minor'] = 43
    result = analyze(old, new, other_device)
    assert result['reported_identity_matches'] == []
    assert result['reported_descriptor_identity_changes'] == []


@pytest.mark.parametrize('field,value', [('fd.ino', 0), ('fd.ino', True), ('fd.ino', None),
    ('fd.dev.major', -1), ('fd.dev.minor', None), ('fd.num', True),
    ('proc.pid.ts', None), ('fd.name', '/fake/../escape')])
def test_unresolved_native_object_identity_stays_an_explicit_gap(field, value):
    value_row = event()
    value_row[field] = value
    result = analyze(value_row)
    assert result['observations'] == []
    assert result['unresolved_events']


@pytest.mark.parametrize('result', [-13, 0])
def test_failed_or_eof_io_does_not_supply_object_access(result):
    value = event()
    value['evt.rawres'] = result
    assert analyze(value)['observations'] == []


def test_successful_open_is_an_identity_observation_without_completed_byte_read():
    value = event()
    value.update({'evt.type': 'openat', 'evt.rawres': 3, 'evt.arg.flags': 'O_RDONLY'})
    observed = analyze(value)['observations'][0]
    assert observed['bytes_transferred'] is None
    assert observed['content_io_observed'] is False


def test_an_open_returning_a_different_descriptor_cannot_supply_identity():
    value = event()
    value.update({'evt.type': 'openat', 'evt.rawres': 9, 'evt.arg.flags': 'O_RDONLY'})
    assert analyze(value)['observations'] == []


def test_duplicate_or_foreign_unbound_metadata_does_not_supply_an_alias():
    value = event()
    with pytest.raises(ValueError, match='duplicate'):
        analyze(value, value)
    value['container.full_id'] = 'b' * 64
    with pytest.raises(ValueError, match='exact native container identity'):
        analyze(value)


def test_foreign_short_id_with_target_full_id_cannot_supply_object_observations():
    foreign = event(2, path='/foreign')
    foreign['container.id'] = 'foreign'
    result = analyze(event(), foreign)
    assert len(result['observations']) == 1
    assert result['reported_identity_matches'] == []
