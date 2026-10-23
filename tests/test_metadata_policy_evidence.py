import copy
import json
from pathlib import Path

import pytest

from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore
from tests.test_policy_evidence import review


def fixture(tmp_path):
    store, rid, original = review(tmp_path)
    store.record_file_enforcement(rid, **original)
    base_policy = json.loads(original["native_policy"])["policy"]
    outcomes = {}
    trial = {"image_id": "sha256:" + "b" * 64, "image_archive_sha256": "c" * 64,
             "sandboxes_stopped": {"permissive": True, "restricted": True}, "outcomes": outcomes}
    for kind in ("permissive", "restricted"):
        policy = copy.deepcopy(base_policy)
        if kind == "permissive":
            policy["filesystem_policy"]["read_only"].append("/opt/skillguard-canary/private.txt")
        policy["filesystem_policy"]["read_write" if kind == "permissive" else "read_only"].append(
            "/opt/skillguard-canary/metadata.txt")
        trial[kind + "_native"] = {"policy": policy}
        trial[kind + "_container"] = {"image_id": trial["image_id"],
                                      "id": ("a" if kind == "permissive" else "d") * 64}
        outcomes[kind] = {"uid": 1000, "gid": 1000, "file_uid_before": 1000,
            "file_gid_before": 0, "mode_before": "0o640", "read_passed": True,
            "chmod_allowed": True, "chown_allowed": True, "file_uid_after": 1000,
            "file_gid_after": 1000, "mode_after": "0o600", "content_write_errno": 13,
            "content_write_allowed": kind == "permissive",
            "content_after": "XAKE_METADATA_CANARY" if kind == "permissive"
                              else "FAKE_METADATA_CANARY"}
    report = {"scope": "Native fake metadata policy diagnostic; not candidate enforcement",
              "complete": False, "activation_permitted": False,
              "candidate_sha256": store.get(rid)["candidate_sha256"], "native_trial": trial}
    return store, rid, report


def record(store, rid, report):
    artifacts = {"trial.json": json.dumps(report["native_trial"]).encode(),
                 "guest.py": b"recorded operator fixture", "probe.py": b"fake metadata fixture"}
    report["artifacts"] = {name:digest(raw) for name, raw in artifacts.items()}
    return store.record_metadata_policy_probe(rid, report=json.dumps(report).encode(),
                                              artifacts=artifacts)


def add_root_control(report):
    trial = report['native_trial']
    for kind in ('permissive', 'restricted'):
        paths = trial[kind + '_native']['policy']['filesystem_policy']
        paths['read_write' if kind == 'permissive' else 'read_only'].append(
            '/opt/skillguard-canary/root-metadata.txt')
        trial['outcomes'][kind]['root_owned_control'] = {
            'effective_uid': 1000, 'effective_gid': 1000,
            'effective_capabilities': '0000000000000000',
            'file_uid_before': 0, 'file_gid_before': 0, 'mode_before': '0o444',
            'parent_uid': 0, 'parent_mode': '0o755', 'read_passed': True,
            'content_write_allowed': False, 'content_write_errno': 13,
            'chmod_allowed': False, 'chmod_errno': 1, 'chown_allowed': False, 'chown_errno': 1,
            'file_uid_after': 0, 'file_gid_after': 0, 'mode_after': '0o444',
            'content_after': 'FAKE_ROOT_METADATA_CANARY'}


def test_root_owned_native_control_is_separate_from_agent_owned_policy_gap(tmp_path):
    store, rid, report = fixture(tmp_path)
    add_root_control(report)
    event = record(store, rid, report)
    boundary = event['data']['root_owned_control']
    assert boundary['status'] == 'bounded_root_owned_metadata_denial_verified'
    assert boundary['effective_uid'] == 1000
    assert boundary['chmod_denied'] and boundary['ownership_change_denied']
    assert event['data']['chmod_denied'] is False
    assert store.evidence(rid)['E11']['value']['root_owned_control'] == boundary
    assert store.decide(rid)['activation_permitted'] is False


@pytest.mark.parametrize('changed', ['capabilities', 'effective_uid', 'owner', 'group', 'mode',
                                    'parent', 'read', 'chmod', 'chown', 'write', 'content',
                                    'errno', 'missing_control', 'missing_grant'])
def test_root_owned_boundary_requires_exact_native_identity_and_denials(tmp_path, changed):
    store, rid, report = fixture(tmp_path)
    add_root_control(report)
    trial = report['native_trial']
    outcome = trial['outcomes']['restricted']['root_owned_control']
    fields = {'capabilities': 'effective_capabilities', 'effective_uid': 'effective_uid',
              'owner': 'file_uid_before', 'group': 'file_gid_after', 'mode': 'mode_after',
              'parent': 'parent_uid', 'read': 'read_passed', 'chmod': 'chmod_allowed',
              'chown': 'chown_allowed', 'write': 'content_write_allowed',
              'content': 'content_after', 'errno': 'chmod_errno'}
    if changed == 'missing_control':
        del trial['outcomes']['restricted']['root_owned_control']
    elif changed == 'missing_grant':
        trial['restricted_native']['policy']['filesystem_policy']['read_only'].remove(
            '/opt/skillguard-canary/root-metadata.txt')
    else:
        outcome[fields[changed]] = None
    with pytest.raises(ValueError):
        record(store, rid, report)


def source_fixture(tmp_path):
    from skillguard.envelope.schema import BehavioralEnvelope

    store, _, report = fixture(tmp_path)
    path = tmp_path / 'source-pending.json'
    path.write_text(json.dumps({'id': 'abcdef13', 'subsystem': 'skills', 'action': 'batch',
        'payload': {'action': 'batch', 'operations': [
            {'action': 'create', 'name': 'source-receipts', 'content': '# Fake source fixture'},
            {'action': 'write_file', 'name': 'source-receipts',
             'file_path': 'scripts/parse_receipt.py', 'file_content': 'pass\n'}]}}))
    rid = store.capture(path)
    target = '/opt/skillguard-candidate/scripts/parse_receipt.py'
    store.record_contract(rid, BehavioralEnvelope(files_read={target}))
    base = store.record_policy_draft(rid, runtime_read_only=['/usr'])['data']['policy']
    report['candidate_sha256'] = store.get(rid)['candidate_sha256']
    for kind in ('permissive', 'restricted'):
        policy = copy.deepcopy(base)
        if kind == 'permissive':
            policy['filesystem_policy']['read_only'].append('/opt/skillguard-canary/private.txt')
        policy['filesystem_policy']['read_write' if kind == 'permissive' else 'read_only'].append(
            '/opt/skillguard-canary/metadata.txt')
        report['native_trial'][kind + '_native']['policy'] = policy
    add_root_control(report)
    parser = Path(store.get(rid)['snapshot']) / 'scripts/parse_receipt.py'
    identity = digest(parser.read_bytes())
    dirs = {name: {'uid': 0, 'gid': 0, 'mode': '0o555'} for name in ('scripts', 'candidate')}
    for kind in ('permissive', 'restricted'):
        report['native_trial']['outcomes'][kind]['candidate_source_control'] = {
            'parser_sha256_before': identity, 'parser_sha256_after': identity,
            'file_uid_before': 0, 'file_gid_before': 0, 'mode_before': '0o444',
            'file_uid_after': 0, 'file_gid_after': 0, 'mode_after': '0o444',
            'directories_before': copy.deepcopy(dirs), 'directories_after': copy.deepcopy(dirs),
            **{name + '_allowed': False for name in (
                'content_write', 'chmod', 'chown', 'unlink', 'rename',
                'parent_chmod', 'root_chmod')},
            **{name + '_errno': 13 for name in ('content_write', 'unlink', 'rename')},
            **{name + '_errno': 1 for name in ('chmod', 'chown', 'parent_chmod', 'root_chmod')}}
    return store, rid, report


def test_actual_source_denial_stays_separate_from_agent_owned_policy_gap(tmp_path):
    store, rid, report = source_fixture(tmp_path)
    event = record(store, rid, report)
    value = event['data']['candidate_source_control']
    assert value['status'] == 'bounded_selected_parser_source_denial_verified'
    assert value['parser_sha256'] == digest(b'pass\n')
    assert value['unlink_denied'] and value['rename_denied']
    assert event['data']['chmod_denied'] is False  # Agent-owned fake file still changes.
    assert store.evidence(rid)['E11']['value']['candidate_source_control'] == value
    assert store.decide(rid)['activation_permitted'] is False


@pytest.mark.parametrize('changed', ['parser', 'uid', 'mode', 'unlink', 'rename', 'directory',
                                    'directory_boolean', 'errno', 'missing_control',
                                    'missing_root', 'host_error'])
def test_source_boundary_requires_current_parser_hash_and_both_native_denials(tmp_path, changed):
    store, rid, report = source_fixture(tmp_path)
    outcomes = report['native_trial']['outcomes']
    value = outcomes['restricted']['candidate_source_control']
    fields = {'parser': 'parser_sha256_after', 'uid': 'file_uid_before', 'mode': 'mode_after',
              'unlink': 'unlink_allowed', 'rename': 'rename_allowed', 'errno': 'unlink_errno'}
    if changed in fields:
        value[fields[changed]] = None
    elif changed == 'directory':
        value['directories_after']['candidate']['uid'] = 1000
    elif changed == 'directory_boolean':
        value['directories_after']['candidate']['uid'] = False
    elif changed == 'missing_control':
        del outcomes['restricted']['candidate_source_control']
    elif changed == 'missing_root':
        del outcomes['restricted']['root_owned_control']
    else:
        report['error'] = 'Failed host verification'
    with pytest.raises(ValueError):
        record(store, rid, report)


def test_native_metadata_gap_persists_without_replacing_file_canary_or_approving(tmp_path):
    store, rid, report = fixture(tmp_path)
    event = record(store, rid, report)
    assert event["data"]["status"] == "metadata_denial_gap_verified"
    reopened = ReviewStore(store.root)
    assert reopened.get(rid)["latest"]["file_enforcement"]["status"] == "file_canary_verified"
    value = reopened.evidence(rid)["E11"]["value"]
    assert value["candidate_executed"] is False
    assert value["chmod_denied"] is False
    assert "FAKE_METADATA_CANARY" not in json.dumps(value)
    assert any("permission/ownership" in reason for reason in reopened.decide(rid)["reasons"])
    assert reopened.decide(rid)["activation_permitted"] is False


@pytest.mark.parametrize("changed", ["image", "policy", "uid", "owner", "mode", "content",
                                     "write", "cleanup", "scope", "same_container"])
def test_inconsistent_or_missing_native_metadata_controls_cannot_be_recorded(tmp_path, changed):
    store, rid, report = fixture(tmp_path)
    trial = report["native_trial"]
    outcome = trial["outcomes"]["restricted"]
    if changed == "image":
        trial["restricted_container"]["image_id"] = "sha256:" + "d" * 64
    elif changed == "policy":
        trial["restricted_native"]["policy"]["filesystem_policy"]["read_write"].append(
            "/opt/skillguard-canary/metadata.txt")
    elif changed in {"uid", "owner", "mode", "content", "write"}:
        outcome[{"uid":"uid", "owner":"file_gid_after", "mode":"mode_after",
                 "content":"content_after", "write":"content_write_allowed"}[changed]] = None
    elif changed == "cleanup":
        trial["sandboxes_stopped"]["restricted"] = False
    elif changed == "same_container":
        trial["restricted_container"]["id"] = trial["permissive_container"]["id"]
    else:
        report["complete"] = True
    with pytest.raises(ValueError):
        record(store, rid, report)
    assert "metadata_policy_probe" not in store.get(rid)["latest"]
