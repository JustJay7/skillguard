import copy
import json
from pathlib import Path

import pytest

from scripts.analyze_native_socket_controls import verify_controls
from skillguard.review.snapshot import digest
from skillguard.traces.sysdig import parse_sysdig


def fixture():
    folder = Path(__file__).parent / 'fixtures'
    text = (folder / 'sysdig-native-socket-controls.jsonl').read_text()
    source = json.loads((folder / 'sysdig-native-socket-controls-source.json').read_text())
    assert digest(text.encode()) == source['fixture_sha256']
    return text, source


def test_actual_native_ipc_transfers_and_unsuccessful_udp_remain_partial():
    text, source = fixture()
    report = verify_controls(text, container_id=source['container_id'],
                             checks=source['socket_ipc_checks'])
    assert report['fixed_ipc_controls_passed'] is True
    assert len(report['controls']) == 6
    assert report['udp_completed'] is False and report['udp_errno'] == 89
    assert report['tcp_peer_controls_passed'] is False
    assert report['complete'] is False and report['activation_permitted'] is False
    evidence = parse_sysdig(text, container_id=source['container_id'])
    assert evidence.envelope.files_read == evidence.envelope.files_written == set()
    assert all(r['payload_observed'] is False for r in evidence.socket_io)


@pytest.mark.parametrize('fault', ['entry', 'fd', 'pid', 'start', 'count', 'same_fd',
                                 'missing', 'udp', 'gap', 'duplicate'])
def test_missing_or_changed_independent_controls_are_rejected(fault):
    text, source = fixture()
    checks = copy.deepcopy(source['socket_ipc_checks'])
    rows = [json.loads(line) for line in text.splitlines()]
    control = next(r for r in rows if r['evt.type'] == 'sendmsg' and r['evt.dir'] == '<')
    entry = next(r for r in rows if r['evt.type'] == 'sendmsg' and r['evt.dir'] == '>')
    if fault == 'entry':
        rows.remove(entry)
    elif fault == 'fd':
        entry['fd.num'] += 1
    elif fault == 'pid':
        control['proc.pid'] += 1
    elif fault == 'start':
        control['proc.pid.ts'] += 1
    elif fault == 'count':
        checks['unix_sent'] = True
    elif fault == 'same_fd':
        checks['unix_fds'][1] = checks['unix_fds'][0]
    elif fault == 'missing':
        rows.remove(control)
    elif fault == 'udp':
        checks['udp_sent'] = 16
    elif fault == 'gap':
        next(r for r in rows if r['evt.type'] == 'sendto' and r['evt.rawres'] == -89)[
            'evt.rawres'] = -1
    else:
        rows.append(control)
    with pytest.raises(ValueError):
        verify_controls('\n'.join(json.dumps(r) for r in rows),
                        container_id=source['container_id'], checks=checks)
