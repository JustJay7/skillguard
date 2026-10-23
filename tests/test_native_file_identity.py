import copy
import json
from pathlib import Path

import pytest

from scripts.analyze_native_file_identity import verify_controls
from skillguard.review.snapshot import digest


def fixture():
    folder = Path(__file__).parent / 'fixtures'
    text = (folder / 'sysdig-native-file-identity.jsonl').read_text()
    source = json.loads((folder / 'sysdig-native-file-identity-source.json').read_text())
    assert digest(text.encode()) == source['fixture_sha256']
    return text, source


def test_actual_native_stale_paths_and_object_changes_pass_fixed_controls_only():
    text, source = fixture()
    result = verify_controls(text, container_id=source['container_id'],
                             checks=source['file_identity_checks'])
    assert result['fixed_controls_passed'] is True
    assert result['stale_reported_path_observed'] is True
    assert len(result['controls']) == 6
    assert result['descriptor_reuse_control_passed'] is True
    assert result['replacement_object_control_passed'] is True
    assert result['complete'] is False and result['activation_permitted'] is False


@pytest.mark.parametrize('fault', ['inode', 'device', 'fd', 'process', 'entry', 'rename',
    'unlink', 'close', 'count', 'content', 'same_object', 'reuse', 'duplicate'])
def test_changed_lifetimes_or_control_identity_cannot_be_promoted(fault):
    text, source = fixture()
    checks = copy.deepcopy(source['file_identity_checks'])
    rows = [json.loads(line) for line in text.splitlines()]
    read = next(r for r in rows if r['evt.type'] == 'read' and r['evt.dir'] == '<')
    if fault == 'inode':
        read['fd.ino'] += 1
    elif fault == 'device':
        read['fd.dev.minor'] += 1
    elif fault == 'fd':
        read['fd.num'] += 1
    elif fault == 'process':
        read['proc.pid.ts'] += 1
    elif fault == 'entry':
        entry = next(r for r in rows if r['evt.type'] == 'read' and r['evt.dir'] == '>')
        rows.remove(entry)
    elif fault in ('rename', 'unlink'):
        mutation = next(r for r in rows if r['evt.type'] == fault + 'at' and r['evt.dir'] == '<')
        rows.remove(mutation)
    elif fault == 'close':
        rows = [r for r in rows if not (r['evt.type'] == 'close' and r['evt.dir'] == '<'
            and r.get('fd.name') == checks['paths']['source'])]
    elif fault == 'count':
        checks['observations']['hardlink_read']['bytes_read'] = True
    elif fault == 'content':
        checks['observations']['hardlink_read']['content_correct'] = False
    elif fault == 'same_object':
        checks['observations']['replacement_read']['inode'] = (
            checks['observations']['original_open']['inode'])
    elif fault == 'reuse':
        checks['observations']['reused_descriptor_read']['fd'] += 1
    else:
        rows.append(read)
    with pytest.raises(ValueError):
        verify_controls('\n'.join(json.dumps(r) for r in rows),
                        container_id=source['container_id'], checks=checks)
