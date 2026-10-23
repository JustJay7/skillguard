import copy
import json
from pathlib import Path

import pytest

from scripts.analyze_native_directory_controls import verify_controls
from skillguard.review.snapshot import digest


def fixture():
    folder = Path(__file__).parent / 'fixtures'
    raw = (folder / 'sysdig-native-directory-controls.jsonl').read_text()
    source = json.loads((folder / 'sysdig-native-directory-controls-source.json').read_text())
    assert digest(raw.encode()) == source['fixture_sha256']
    return raw, source


def test_actual_native_writer_mistyped_as_directory_stays_unresolved():
    raw, source = fixture()
    result = verify_controls(raw, container_id=source['container_id'],
                             checks=source['directory_open_checks'])
    assert result['fixed_controls_passed'] is True
    assert result['native_unnamed_file_reported_type'] == 'directory'
    assert result['unnamed_file_actual_control_type'] == 'regular'
    assert result['complete'] is False and result['activation_permitted'] is False


@pytest.mark.parametrize('fault', ['support', 'mode', 'type', 'links', 'descriptor',
                                 'process', 'flags', 'missing_event', 'duplicate_event'])
def test_positive_controls_refuse_missing_or_inconsistent_native_evidence(fault):
    raw, source = fixture()
    checks = copy.deepcopy(source['directory_open_checks'])
    rows = [json.loads(line) for line in raw.splitlines()]
    if fault == 'support':
        checks['tmpfile_supported'] = False
    elif fault == 'mode':
        checks['directory_access_mode'] = 2
    elif fault == 'type':
        checks['tmpfile_is_regular'] = False
    elif fault == 'links':
        checks['tmpfile_link_count'] = 1
    elif fault == 'descriptor':
        checks['tmpfile_fd'] += 1
    elif fault == 'process':
        rows[1]['proc.pid.ts'] += 1
    elif fault == 'flags':
        rows[1]['evt.arg.flags'] = 'O_RDONLY|O_DIRECTORY|O_TMPFILE'
    elif fault == 'missing_event':
        rows.pop()
    else:
        rows.append(rows[1])
    with pytest.raises(ValueError):
        verify_controls('\n'.join(json.dumps(r) for r in rows),
                        container_id=source['container_id'], checks=checks)
