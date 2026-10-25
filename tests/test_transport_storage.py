import errno
import gzip
from types import SimpleNamespace

import pytest

from scripts import run_receipt_agent_probe as module
from skillguard.review.snapshot import digest


def test_native_transport_is_lossless_and_does_not_keep_a_second_raw_copy(tmp_path):
    raw = b'fictional native transport fixture\n' * 10000
    proof = module.archive_native_transport(tmp_path, raw)
    assert gzip.decompress((tmp_path / proof['archive']).read_bytes()) == raw
    assert proof['original_sha256'] == digest(raw)
    assert proof['original_bytes'] == len(raw)
    assert proof['lossless_verified'] and proof['compressed_bytes'] < len(raw)
    assert not (tmp_path / 'native-job.tar').exists()


def test_native_transport_never_overwrites_previous_evidence(tmp_path):
    target = tmp_path / 'native-job.tar.gz'
    target.write_bytes(b'previous evidence')
    with pytest.raises(FileExistsError):
        module.archive_native_transport(tmp_path, b'replacement')
    assert target.read_bytes() == b'previous evidence'


def test_low_host_storage_stops_before_inference_or_artifact_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    with pytest.raises(OSError) as error:
        module.run(tmp_path, live=True, capture_native=True, runtime='openshell')
    assert error.value.errno == errno.ENOSPC
    assert list(tmp_path.iterdir()) == []
