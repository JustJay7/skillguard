import json
import shutil
from pathlib import Path

import pytest

from skillguard.core import CORE_POLICY, SCOPE, CoreWorkspace, update_guide
from skillguard.review.snapshot import digest


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    return CoreWorkspace(root, root / 'results/core')


def candidate(w, pid='1234abcd', extra=''):
    pending = w.profile / 'pending/skills' / (pid + '.json')
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(json.dumps({'id': pid, 'subsystem': 'skills', 'action': 'batch',
        'payload': {'action': 'batch', 'operations': [
            {'action': 'create', 'name': 'receipt-organizer', 'content': '# Receipt\n' + extra},
            {'action': 'write_file', 'name': 'receipt-organizer',
             'file_path': 'scripts/parse_receipt.py', 'file_content': 'print("fixture")\n'}]}}))
    return w.detect()[-1]


def passing_test(w, rid):
    static = {'overall_status': 'passed', 'incomplete_scans': []}
    w.store.record_static(rid, static)
    return w.store._append(rid, 'core_test', {'passed': True, 'scope': SCOPE,
        'candidate_sha256': w.store.get(rid)['candidate_sha256'],
        'policy_sha256': digest(CORE_POLICY.encode()),
        'static_sha256': digest(json.dumps(static, sort_keys=True).encode())})


def revision(w, rid):
    review = w.store.get(rid)
    return review['history'][-1]['seq'] if review['history'] else 0


def test_app_stages_exact_repaired_bundle_and_preserves_update_bytes(workspace, monkeypatch):
    w = workspace
    source = w.root / 'skills/repaired-v8/receipt-organizer'
    source.mkdir(parents=True)
    (source / 'scripts').mkdir()
    guide = '---\nversion: 0.2.7\n---\nRepaired guide with after-input refresh.\n'
    (source / 'SKILL.md').write_text(guide)
    (source / 'scripts/parse_receipt.py').write_text('unchanged parser\n')
    calls = []
    detections = iter([[], ['captured'], [], ['updated']])
    monkeypatch.setattr(w, 'detect', lambda: next(detections))
    monkeypatch.setattr(w, 'native', lambda *a: calls.append(a) or {'staged': True})
    monkeypatch.setattr(w.store, '_append', lambda *a: None)
    monkeypatch.setattr(w.store, 'get', lambda rid: {'latest': {'security_required': {}}})
    assert w.stage_example() == 'captured'
    monkeypatch.setattr(w, 'installed', lambda: {'active': 'old'})
    monkeypatch.setattr(w, 'version', lambda vid: ({}, source))
    assert w.stage_example(update=True, repaired=True) == 'updated'
    for call in calls:
        operations = call[2]['operations']
        assert operations[0]['content'] == guide
        assert operations[1]['file_content'] == 'unchanged parser\n'
    assert calls[1][2]['operations'][0]['action'] == 'patch'


@pytest.mark.parametrize('fault', ['untested', 'stale', 'no_ack', 'static_changed', 'snapshot'])
def test_approval_cannot_bypass_review_integrity_or_operator_scope(workspace, monkeypatch, fault):
    w = workspace
    rid = candidate(w)
    if fault != 'untested':
        passing_test(w, rid)
    seq = revision(w, rid)
    if fault == 'static_changed':
        w.store.record_static(rid, {'overall_status': 'failed', 'incomplete_scans': []})
        seq = revision(w, rid)
    elif fault == 'snapshot':
        (Path(w.store.get(rid)['snapshot']) / 'SKILL.md').write_text('Changed after review')
    monkeypatch.setattr(w, 'native', lambda *a, **kw: pytest.fail('No native apply allowed'))
    with pytest.raises(ValueError):
        w.approve(rid, revision=seq - 1 if fault == 'stale' else seq,
                  acknowledge_limits=fault != 'no_ack')
    assert w.installed()['active'] is None


def test_reject_removes_only_the_matching_native_pending_write(workspace, monkeypatch):
    w = workspace
    rid = candidate(w)

    def native(profile, action, pending_id):
        assert profile == w.profile and action == 'discard'
        path = profile / 'pending/skills' / (pending_id + '.json')
        path.unlink()
        return {'removed': True}

    monkeypatch.setattr(w, 'native', native)
    assert w.reject(rid, revision=revision(w, rid))['archive_preserved']
    assert not w.detect() and not w.eligible(w.store.get(rid))


def test_install_is_hash_bound_and_rollback_preserves_both_versions(workspace, monkeypatch):
    w = workspace
    rid = candidate(w)
    passing_test(w, rid)

    def install(profile, operation, payload=None, pending_id=None):
        if operation == 'apply':
            active = profile / 'skills/receipt-organizer'
            shutil.copytree(Path(w.store.get(selected[0])['snapshot']), active)
            return {'success': True}
        (profile / 'pending/skills' / (pending_id + '.json')).unlink()
        return {'removed': True}

    selected = [rid]
    monkeypatch.setattr(w, 'native', install)
    first = w.approve(rid, revision=revision(w, rid), acknowledge_limits=True, require_agent=False)
    assert w.version(first['id'])[0]['candidate_sha256'] == first['candidate_sha256']
    second_rid = candidate(w, 'abcd1234', 'Second guide version\n')
    passing_test(w, second_rid)
    selected[0] = second_rid
    # Fixture a prior valid installed update, without simulating a create over it.
    pending = w.profile / 'pending/skills/abcd1234.json'
    state = w.installed()
    w.save_state({**state, 'active': None})
    second = w.approve(second_rid, revision=revision(w, second_rid),
                       acknowledge_limits=True, require_agent=False)
    w.save_state({**w.installed(), 'previous': first['id']})
    assert not pending.exists()
    restored = w.rollback(expected_active=second['id'])
    assert restored['id'] == first['id'] and w.installed()['previous'] == second['id']
    assert w.version(second['id'])[0]['candidate_sha256'] == second['candidate_sha256']
    with pytest.raises(ValueError, match='changed'):
        w.rollback(expected_active=second['id'])
    manifest_path = w.workspace / 'versions' / first['id'] / 'version.json'
    original_manifest = manifest_path.read_text()
    manifest_path.write_text(json.dumps({**json.loads(original_manifest),
                                         'security_decision': 'restricted_pass'}))
    with pytest.raises(ValueError, match='operator approval'):
        w.version(first['id'])
    manifest_path.write_text(original_manifest)
    installed = w.version(first['id'])[1]
    (installed / 'scripts/parse_receipt.py').write_text('changed installed code')
    with pytest.raises(ValueError, match='changed'):
        w.version(first['id'])


def test_installed_manifest_requires_a_matching_recorded_approval(workspace):
    w = workspace
    rid = candidate(w)
    passing_test(w, rid)
    version_id = 'a' * 32
    folder = w.workspace / 'versions' / version_id
    skill = folder / 'profile/skills/receipt-organizer'
    review = w.store.get(rid)
    shutil.copytree(review['snapshot'], skill)
    (folder / 'version.json').write_text(json.dumps({'id': version_id,
        'review_id': rid, 'candidate_sha256': review['candidate_sha256'],
        'policy_sha256': digest(CORE_POLICY.encode())}))
    with pytest.raises(ValueError, match='operator approval'):
        w.version(version_id)


def test_repeated_updates_create_a_new_version_and_reject_unsupported_versions():
    template = '---\nversion: 1.0.0\n---\nReceipt guide.'
    first = update_guide(template, template)
    second = update_guide(template, first)
    assert 'version: 1.1.0' in first and 'version: 1.2.0' in second
    with pytest.raises(ValueError, match='supported version'):
        update_guide(template, 'unversioned guide')
