import json
import zipfile

import pytest

from scripts import build_demo


@pytest.fixture
def release(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    assets = root / 'skillguard/ui'
    assets.mkdir(parents=True)
    for name in ('demo.html', 'demo.js', 'demo.css'):
        (assets / name).write_text('offline public asset ' + name)
    (root / 'LICENSE').write_text('MIT test fixture')
    (root / '.env').write_text('NEBIUS_API_KEY=private-not-for-release')
    (root / 'results').mkdir()
    monkeypatch.setattr(build_demo, 'payload', lambda root: {'source_workflow': 'offline-fixture'})
    return root


def test_release_is_reproducible_allowlisted_and_excludes_private_workspace(release):
    first = build_demo.build(release)
    second = build_demo.build(release)
    assert first['sha256'] == second['sha256']
    with zipfile.ZipFile(release / first['archive']) as archive:
        assert set(archive.namelist()) == {'index.html', 'demo.js', 'demo.css', 'evidence.json',
                                         'provenance.json', 'README.txt', 'LICENSE'}
        assert all(b'private-not-for-release' not in archive.read(n) for n in archive.namelist())
        proof = json.loads(archive.read('provenance.json'))
        for name, sha in proof.items():
            assert build_demo.digest(archive.read(name)) == sha
    assert first['new_model_requests'] == 0 and not first['public_upload_performed']


@pytest.mark.parametrize('fault', ['extra_file', 'symlink', 'directory'])
def test_unsafe_release_destination_fails_without_publishing_or_deleting(release, fault):
    folder = release / 'dist/skillguard-demo'
    folder.mkdir(parents=True)
    if fault == 'extra_file':
        (folder / '.env').write_text('private')
    elif fault == 'symlink':
        (folder / 'index.html').symlink_to(release / '.env')
    else:
        (folder / 'index.html').mkdir()
    with pytest.raises(ValueError, match='allowlisted'):
        build_demo.build(release)
    assert (release / '.env').read_text() == 'NEBIUS_API_KEY=private-not-for-release'
    assert not (release / 'dist/skillguard-demo.zip').exists()
