import io
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from skillguard.evaluation.receipt_template import template_path
from skillguard.review.snapshot import artifact_tree_digest, digest


def setup_template(tmp_path):
    (tmp_path / 'config').mkdir()
    source = Path(__file__).resolve().parents[1] / 'config'
    for name in ('receipt-agent-base.tar', 'receipt-agent-template.json'):
        shutil.copyfile(source / name, tmp_path / 'config' / name)
    return tmp_path


def test_packaged_task_is_reproducible_disabled_and_preserves_existing_proposals(tmp_path):
    root = setup_template(tmp_path)
    path = template_path(root)
    value = json.loads(path.read_text())
    assert value['execution_enabled'] is False and value['status'] == 'prepared_no_inference'
    assert value['maximum_model_requests'] == 6 and value['max_output_tokens_per_request'] == 2000
    assert value['enable_thinking'] is False
    task = Path(value['task']['task'])
    assert artifact_tree_digest(task) == value['template']['task_sha256']
    assert task.is_relative_to(root / 'results')
    original = path.read_bytes()
    assert template_path(root) == path and path.read_bytes() == original
    assert b'Copyright' in (task / 'tests/custom_grader_runner.py').read_bytes()


@pytest.mark.parametrize('fault', ['bytes', 'symlink', 'traversal', 'existing_default'])
def test_template_refuses_changed_bytes_unsafe_entries_and_existing_base(tmp_path, fault):
    root = setup_template(tmp_path)
    archive = root / 'config/receipt-agent-base.tar'
    if fault == 'bytes':
        archive.write_bytes(b'changed')
    elif fault == 'existing_default':
        (root / 'results').mkdir()
        (root / 'results/receipt-live-probe-proposal.json').write_text('preserve')
    else:
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w') as bundle:
            member = tarfile.TarInfo('../escape' if fault == 'traversal' else 'link')
            if fault == 'symlink':
                member.type, member.linkname = tarfile.SYMTYPE, '/outside'
            bundle.addfile(member)
        archive.write_bytes(output.getvalue())
        source = root / 'config/receipt-agent-template.json'
        value = json.loads(source.read_text())
        value['template']['archive_sha256'] = digest(archive.read_bytes())
        source.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        template_path(root)
    assert not (root / 'results/receipt-live-probe-agent-record-complete-2026-10-22.json').exists()
    assert not (root / 'escape').exists()
