import io
import json
import tarfile

import pytest

from skillguard.evaluation.receipt_output_recovery import answer_from_archive, checked_answer
from skillguard.review.snapshot import digest


def bundle(fault=None):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w') as archive:
        answer = tarfile.TarInfo('out/answer.json')
        body = b'{"actual":"saved file"}'
        if fault in {'symlink', 'hardlink'}:
            answer.type = tarfile.SYMTYPE if fault == 'symlink' else tarfile.LNKTYPE
            answer.linkname = '/opt/fake/private-note.txt'
        else:
            answer.size = len(body)
        archive.addfile(answer, io.BytesIO(body) if answer.isfile() else None)
        link = tarfile.TarInfo('out/context.txt' if fault != 'path' else 'out/../escape')
        link.type = tarfile.SYMTYPE
        link.linkname = '/opt/fake/private-note.txt'
        archive.addfile(link)
        if fault == 'duplicate':
            archive.addfile(answer, io.BytesIO(body))
    return raw.getvalue(), body


@pytest.mark.parametrize('fault', [None, 'symlink', 'hardlink', 'path', 'duplicate'])
def test_recover_regular_answer_without_resolving_untrusted_links(fault):
    raw, body = bundle(fault)
    if fault:
        with pytest.raises(ValueError):
            answer_from_archive(raw)
    else:
        saved, inventory = answer_from_archive(raw)
        assert saved == body
        assert inventory[-1]['link_target'] == '/opt/fake/private-note.txt'


@pytest.mark.parametrize('fault', [None, 'active', 'identity', 'archive', 'original'])
def test_recovery_requires_the_same_stopped_container_and_unchanged_bytes(tmp_path, fault):
    recovery = tmp_path / 'output-recovery'
    recovery.mkdir()
    adapter = tmp_path / 'trial/environment/openshell'
    adapter.mkdir(parents=True)
    (adapter / 'binding.json').write_text(json.dumps({'container_id': 'container',
                                                    'image_id': 'image'}))
    original = b'{"run_id":"run"}'
    raw, body = bundle()
    _, inventory = answer_from_archive(raw)
    before = {'running': False, 'container_id': 'container', 'image_id': 'image',
              'finished_at': 'recorded-stop'}
    proof = {'container_before': before, 'container_after': before,
        'original_report_sha256': digest(original), 'archive_sha256': digest(raw),
        'answer_sha256': digest(body), 'inventory': inventory, 'source': '/workspace/out',
        'agent_or_model_execution': False}
    if fault == 'active':
        before['running'] = True
    elif fault == 'identity':
        before['container_id'] = 'different'
    proof_raw = json.dumps(proof).encode()
    (recovery / 'proof.json').write_bytes(proof_raw)
    (recovery / 'out.tar').write_bytes(raw + b'changed' if fault == 'archive' else raw)
    (recovery / 'original-report.json').write_bytes(original + b' ' if fault == 'original'
                                                    else original)
    report = {'run_id': 'run', 'native_trial': str(tmp_path / 'trial/result.json'),
        'answer_export_recovery': {'proof_sha256': digest(proof_raw),
            'archive_sha256': digest(raw), 'original_report_sha256': digest(original)}}
    if fault:
        with pytest.raises(ValueError):
            checked_answer(tmp_path, report)
    else:
        answer, attachments = checked_answer(tmp_path, report)
        assert answer == body and len(attachments) == 3
