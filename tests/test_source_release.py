import json
import zipfile

import pytest

from scripts import build_source_release


@pytest.fixture
def release(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    (root / '.env').write_text('NEBIUS_API_KEY=secret-fixture-not-public')
    (root / 'README.md').write_text('Public source fixture')
    (root / 'results').mkdir()
    folder = root / 'dist/skillguard-demo'
    folder.mkdir(parents=True)
    for name in ('index.html', 'demo.js', 'demo.css', 'evidence.json', 'provenance.json',
                 'LICENSE', 'README.txt'):
        (folder / name).write_text('public demo fixture')
    monkeypatch.setattr(build_source_release.subprocess, 'check_output',
                        lambda *a, **k: b'README.md\0.env\0')
    return root


def test_source_export_does_not_include_git_history_or_private_environment(release):
    report = build_source_release.build(release)
    with zipfile.ZipFile(release / report['archive']) as archive:
        assert '.env' not in archive.namelist()
        assert all(not n.startswith('.git/') for n in archive.namelist())
        proof = json.loads(archive.read('RELEASE-PROVENANCE.json'))
        for name, sha in proof.items():
            assert build_source_release.digest(archive.read(name)) == sha
        assert all(b'secret-fixture-not-public' not in archive.read(n) for n in archive.namelist())
    assert not report['public_upload_performed']


@pytest.mark.parametrize('fault', ['credential', 'symlink'])
def test_source_export_refuses_secrets_or_linked_sources(release, fault):
    if fault == 'credential':
        (release / 'README.md').write_text('secret-fixture-not-public')
    else:
        (release / 'README.md').unlink()
        (release / 'README.md').symlink_to(release / '.env')
    with pytest.raises(ValueError):
        build_source_release.build(release)
    assert not (release / 'dist/skillguard-source.zip').exists()
