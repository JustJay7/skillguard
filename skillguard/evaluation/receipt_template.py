"""Materialize the fixed fictional app task without copying private run history."""
from __future__ import annotations

import io
import json
import tarfile
import uuid
from pathlib import Path

from skillguard.review.snapshot import artifact_tree_digest, digest


def template_path(root: Path) -> Path:
    target = root / 'results/receipt-live-probe-agent-record-complete-2026-10-22.json'
    if target.exists():
        return target  # Preserve existing development proposals and their exact identities.
    default = root / 'results/receipt-live-probe-proposal.json'
    if default.exists():
        raise ValueError('Existing base proposal must not be replaced')
    source = json.loads((root / 'config/receipt-agent-template.json').read_text())
    raw = (root / 'config/receipt-agent-base.tar').read_bytes()
    if len(raw) > 2_000_000 or digest(raw) != source['template']['archive_sha256']:
        raise ValueError('Packaged fictional task changed')
    destination = root / 'results/integration' / ('receipt-template-' + uuid.uuid4().hex[:8])
    destination.mkdir(mode=0o700, parents=True)
    task = destination / 'task'
    with tarfile.open(fileobj=io.BytesIO(raw)) as bundle:
        members = bundle.getmembers()
        if len(members) > 32 or any(not m.isfile() or Path(m.name).is_absolute()
                or '..' in Path(m.name).parts for m in members):
            raise ValueError('Only bounded regular task files permitted')
        bundle.extractall(task, filter='data')
    expected = source['template']
    files = {p.relative_to(task).as_posix(): digest(p.read_bytes())
             for p in task.rglob('*') if p.is_file()}
    if (files != expected['files'] or artifact_tree_digest(task) != expected['task_sha256']):
        raise ValueError('Packaged native task identity differs')
    source['task']['task'] = str(task.resolve())
    source['task']['task_sha256'] = artifact_tree_digest(task)
    source['authorization'] = 'Prepared only; requires an authenticated app action and fresh claim'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(source, indent=2) + '\n')
    default.write_bytes(target.read_bytes())
    skill = task / 'environment/skills/receipt-organizer'
    # Only source-bound app trials may use this minimal task descriptor.
    (root / 'results/receipt-agent-tasks-latest.json').write_text(json.dumps({
        'candidate_sha256': artifact_tree_digest(skill),
        'parser_sha256': digest((skill / 'scripts/parse_receipt.py').read_bytes()),
        'scope': 'Fixed app task template only; not historical agent evidence'}, indent=2) + '\n')
    return target
