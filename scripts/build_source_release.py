"""Prepare an inspected source archive without Git history or private runtime data."""
from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

from dotenv import dotenv_values

from skillguard.review.snapshot import digest

ROOT_FILES = {'README.md', 'LICENSE', 'pyproject.toml', 'Makefile', '.gitignore',
              '.env.example', 'AGENTS.md', 'DECISIONS.md', 'PROGRESS.md'}
PREFIXES = {'skillguard', 'scripts', 'tests', 'skills', 'config', 'docs'}
EVIDENCE = {'oct23-security-product-verification.json', 'oct23-security-product-history.json',
            'oct23-release-tests.txt', 'demo-build.json', 'demo-render-verification.json',
            'public-demo-deployment.json', 'public-demo-browser-verification.json'}


def build(root: Path) -> dict:
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    files = {}
    redacted = []
    for name in names:
        if not name:
            continue
        path = Path(name)
        if name not in ROOT_FILES and path.parts[0] not in PREFIXES and not (
                path.parent == Path('results') and path.name in EVIDENCE):
            continue
        source = root / path
        if source.is_symlink() or not source.is_file() or '.git' in path.parts:
            raise ValueError('Only tracked regular release files are permitted')
        raw = source.read_bytes()
        if path.parts[0] == 'results' and path.suffix == '.json':
            value = json.loads(raw)
            text = json.dumps(value)
            if str(root) in text:
                original_sha = digest(raw)
                text = text.replace(str(root), '<WORKSPACE>')
                value = json.loads(text)
                value['public_export'] = {'private_workspace_paths_redacted': True,
                                         'original_artifact_sha256': original_sha}
                raw = (json.dumps(value, indent=2) + '\n').encode()
                redacted.append(name)
        files[name] = raw
    demo = root / 'dist/skillguard-demo'
    for name in ('index.html', 'demo.js', 'demo.css', 'evidence.json', 'provenance.json',
                 'LICENSE', 'README.txt'):
        p = demo / name
        if p.is_symlink():
            raise ValueError('Regular demo assets required')
        files['recorded-demo/' + name] = p.read_bytes()
    files['results/.gitkeep'] = b''
    files['RELEASE.md'] = b'''# SkillGuard source release

This archive contains source, tests, documentation and an inspectable recorded demo.
It excludes Git history, .env, private runtime stores, raw captures and VM images.
The installed local application and its runtime are not exported.

For the recorded walkthrough, no key or dependencies are needed:
python3 -m http.server 8769 --bind 127.0.0.1 --directory recorded-demo
Open http://127.0.0.1:8769/ . This is replay, not live inference or installation.

For native execution, use Python 3.12+ and the pinned Hermes/SkillEvaluator sources
and Linux OpenShell stack documented in README.md, docs/upstream-pins.json,
config/linux-trace.yaml and docs/core-flow.md. make setup installs Python app
dependencies only; it does not provision the native VM. Credentials belong only
in a local ignored .env. Archived live proposals are not fresh authorizations.

Exported JSON summaries may redact workspace paths and are labeled accordingly.
Retained native proofs belong to the original run, not this source export.
'''
    for key, value in dotenv_values(root / '.env').items():
        if (value and ('KEY' in key or 'TOKEN' in key)
                and any(value.encode() in raw for raw in files.values())):
            raise ValueError('Configured credential found; source release refused')
    if any(Path(n).name == '.env' or n.startswith('.git/') for n in files):
        raise ValueError('Private state must not enter the source archive')
    provenance = {name: digest(raw) for name, raw in files.items()}
    files['RELEASE-PROVENANCE.json'] = (json.dumps(provenance, indent=2) + '\n').encode()
    target = root / 'dist/skillguard-source.zip'
    if target.is_symlink():
        raise ValueError('Regular source archive destination required')
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 23, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    result = {'passed': True, 'archive': str(target.relative_to(root)),
        'sha256': digest(target.read_bytes()), 'files': len(files), 'bytes': target.stat().st_size,
        'workspace_path_redactions': redacted, 'configured_credentials_excluded': True,
        'git_history_included': False, 'private_runtime_included': False,
        'public_upload_performed': False}
    (root / 'results/source-release-build.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    print(json.dumps(build(Path(__file__).resolve().parents[1]), indent=2))
