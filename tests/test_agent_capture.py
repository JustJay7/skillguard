import gzip
import json
from pathlib import Path

import pytest

from skillguard.evaluation.agent_capture import verify_agent_capture
from skillguard.review.snapshot import digest


def fixture():
    row = json.loads((Path(__file__).parent / 'fixtures/agent-private-read.json').read_text())
    cid = row['container.full_id']
    raw = b'OFFLINE ARTIFACT INTEGRITY TEST ONLY'
    artifacts = {'events.jsonl': json.dumps(row).encode(), 'events.scap.gz': gzip.compress(raw),
        'stats.txt': b'Driver Events:1\nDriver Drops:0\nSuppressed by Comm:0\nCaptured Events: 1\n',
        'container.json': json.dumps({'Id': cid}).encode()}
    metadata = {'complete': False, 'activation_permitted': False, 'container_full_id': cid,
        'sysdig_version': 'sysdig version 0.41.4', 'collector_active_after_job': True,
        'metadata_filter': 'container.id=' + cid[:12] + ' and '
            '(fd.name=/opt/fake/private-note.txt or evt.type=execve or evt.type=execveat)',
        'uncompressed_capture_bytes': len(raw), 'uncompressed_capture_sha256': digest(raw),
        'artifacts': {k: digest(v) for k, v in artifacts.items()}}
    artifacts['capture.json'] = json.dumps(metadata).encode()
    return artifacts


def test_actual_native_private_read_projection_has_no_live_or_general_completeness_credit():
    value = verify_agent_capture(fixture())
    assert value['reported_read_bytes'] == 25
    assert value['reported_private_file_reads'][0]['reference'] == 'sysdig:861663'
    assert not value['complete'] and not value['activation_permitted']
    assert value['model_requests'] == value['live_agent_cases_executed'] == 0


def test_streaming_decompression_still_has_a_hard_size_bound(monkeypatch):
    monkeypatch.setattr('skillguard.evaluation.agent_capture.MAX_CAPTURE_BYTES', 1)
    with pytest.raises(ValueError, match='size bound'):
        verify_agent_capture(fixture())


@pytest.mark.parametrize('fault', ['complete', 'active', 'container', 'bytes', 'hash',
                                 'drop', 'event', 'foreign', 'identity'])
def test_native_capture_rejects_tampered_or_promoted_projection(fault):
    artifacts = fixture()
    metadata = json.loads(artifacts['capture.json'])
    if fault in ('complete', 'active', 'container', 'bytes', 'hash'):
        field = {'complete': 'complete', 'active': 'collector_active_after_job',
                 'container': 'container_full_id', 'bytes': 'uncompressed_capture_bytes',
                 'hash': 'uncompressed_capture_sha256'}[fault]
        metadata[field] = True if fault == 'complete' else False if fault == 'active' else 'changed'
    elif fault == 'drop':
        artifacts['stats.txt'] = artifacts['stats.txt'].replace(
            b'Driver Drops:0', b'Driver Drops:1')
    else:
        row = json.loads(artifacts['events.jsonl'])
        row[{'event': 'evt.rawres', 'foreign': 'container.full_id',
             'identity': 'fd.ino'}[fault]] = 0 if fault != 'foreign' else 'b'*64
        artifacts['events.jsonl'] = json.dumps(row).encode()
    if fault != 'event':
        metadata['artifacts'].update({k: digest(v) for k, v in artifacts.items()
                                      if k != 'capture.json'})
    artifacts['capture.json'] = json.dumps(metadata).encode()
    with pytest.raises(ValueError):
        verify_agent_capture(artifacts)


def test_fast_native_compression_preserves_exact_raw_evidence(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from scripts.native_agent_capture import NativeAgentCapture

    capture = NativeAgentCapture(tmp_path, 'offline-format')
    raw = b'fictional native capture\n' * 10000
    (capture.root / 'events.scap').write_bytes(raw)
    monkeypatch.setattr('scripts.native_agent_capture.subprocess.run',
                        lambda *a, **kw: SimpleNamespace(stdout='active', returncode=0))
    capture.finish()
    assert gzip.decompress((capture.root / 'events.scap.gz').read_bytes()) == raw
    metadata = json.loads((capture.root / 'capture.json').read_text())
    assert metadata['uncompressed_capture_sha256'] == digest(raw)
    assert metadata['uncompressed_capture_bytes'] == len(raw)
    assert not (capture.root / 'events.scap').exists()
