"""Verify a regular output recovered from a stopped native container, never a link."""
from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path, PurePosixPath

from skillguard.review.snapshot import digest


def answer_from_archive(raw: bytes) -> tuple[bytes, list[dict]]:
    if len(raw) > 16 * 1024**2:
        raise ValueError('Recovered output archive exceeds its bound')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)) or any(
                PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts for n in names):
            raise ValueError('Recovered output archive has unsafe paths')
        answer = archive.getmember('out/answer.json')
        if not answer.isfile() or answer.size > 1024**2:
            raise ValueError('Recovered answer must be a bounded regular file')
        inventory = [{'name': m.name, 'type': m.type.decode('ascii'),
                      'size': m.size, 'link_target': m.linkname} for m in members]
        return archive.extractfile(answer).read(), inventory


def checked_answer(folder: Path, report: dict) -> tuple[bytes, dict[str, bytes]]:
    recovery = folder / 'output-recovery'
    raw = (recovery / 'out.tar').read_bytes()
    proof_raw = (recovery / 'proof.json').read_bytes()
    proof = json.loads(proof_raw)
    reference = report['answer_export_recovery']
    original = (recovery / 'original-report.json').read_bytes()
    binding = json.loads((Path(report['native_trial']).parent /
                          'environment/openshell/binding.json').read_text())
    before, after = proof['container_before'], proof['container_after']
    answer, inventory = answer_from_archive(raw)
    if (reference != {'proof_sha256': digest(proof_raw), 'archive_sha256': digest(raw),
                      'original_report_sha256': digest(original)}
            or proof['original_report_sha256'] != digest(original)
            or proof['archive_sha256'] != digest(raw)
            or proof['answer_sha256'] != digest(answer) or proof['inventory'] != inventory
            or before != after or before['running'] is not False
            or before['container_id'] != binding['container_id']
            or before['image_id'] != binding['image_id']
            or not before['finished_at']
            or proof['source'] != '/workspace/out'
            or proof.get('agent_or_model_execution') is not False
            or json.loads(original)['run_id'] != report['run_id']):
        raise ValueError('Stopped-container output recovery differs from its source')
    return answer, {'answer-export-recovery.json': proof_raw,
                    'answer-export-recovery.tar': raw,
                    'answer-export-original-report.json': original}
