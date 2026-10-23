import json

import pytest

from skillguard.traces.sysdig import parse_sysdig
from tests.test_sysdig import CONTAINER, rows


def event(kind, **fields):
    return rows()[0] | {"evt.type": kind, "evt.dir": "<", "evt.rawres": 0, **fields}


@pytest.mark.parametrize("kind", ["unlink", "unlinkat", "rmdir", "mkdir", "mkdirat"])
def test_successful_namespace_change_is_write_without_bytes(kind):
    e = event(kind, **{"fs.path.name": "/sandbox/target"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert result.envelope.files_written == {"/sandbox/target"}
    assert not result.envelope.files_read
    assert result.file_mutations[0]["exit_ref"] == f"sysdig:{e['evt.num']}"


@pytest.mark.parametrize("kind", ["rename", "renameat", "renameat2", "link", "linkat"])
def test_rename_and_hardlink_change_both_names_without_claiming_reads(kind):
    e = event(kind, **{"fs.path.source": "/sandbox/a", "fs.path.target": "/sandbox/b"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert result.envelope.files_written == {"/sandbox/a", "/sandbox/b"}
    assert not result.envelope.files_read


@pytest.mark.parametrize("kind", ["symlink", "symlinkat"])
def test_symlink_text_does_not_claim_access_to_referenced_file(kind):
    e = event(kind, **{"fs.path.target": "/private/referenced", "fs.path.source": "/sandbox/link"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert result.envelope.files_written == {"/sandbox/link"}
    assert not result.envelope.files_read


def test_open_truncate_is_actual_mutation_without_a_write_call():
    e = event("openat", **{"evt.rawres": 4, "evt.arg.flags": "O_WRONLY|O_TRUNC",
                           "fs.path.name": "/sandbox/output"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert result.envelope.files_written == {"/sandbox/output"}


def test_create_without_exclusive_success_is_only_possible_mutation():
    e = event("openat", **{"evt.rawres": 4, "evt.arg.flags": "O_RDWR|O_CREAT",
                           "fs.path.name": "/sandbox/existing"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert not result.envelope.files_written
    assert result.path_mutation_capabilities.files_written == {"/sandbox/existing"}


def test_successful_exclusive_create_is_actual_creation():
    e = event("openat", **{"evt.rawres": 4, "evt.arg.flags": "O_WRONLY|O_CREAT|O_EXCL",
                           "fs.path.name": "/sandbox/new"})
    assert parse_sysdig(json.dumps(e), container_id=CONTAINER).envelope.files_written == {
        "/sandbox/new"}


@pytest.mark.parametrize("path", [None, "relative", "<UNKNOWN>/x", "/sandbox/../private"])
def test_unresolved_mutation_path_remains_explicit_gap(path):
    e = event("unlink", **{"fs.path.name": path})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert not result.envelope.files_written
    assert result.unresolved_events


def test_failed_mutation_contributes_no_write():
    e = event("unlink", **{"evt.rawres": -2, "fs.path.name": "/sandbox/missing"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert not result.envelope.files_written
    assert not result.file_mutations


@pytest.mark.parametrize("kind", ["truncate", "ftruncate", "chmod", "setxattr"])
def test_unsupported_native_metadata_does_not_hide_possible_changes(kind):
    e = event(kind, **{"evt.rawres": None})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert result.unresolved_events
    assert not result.envelope.files_written


def test_impossible_positive_namespace_result_is_a_gap():
    e = event("unlinkat", **{"evt.rawres": 1, "fs.path.name": "/sandbox/target"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert not result.envelope.files_written
    assert result.unresolved_events


def test_actual_native_mutations_keep_symlink_text_separate_and_create_uncertain():
    from pathlib import Path

    from skillguard.review.snapshot import digest

    root = Path(__file__).parent / "fixtures"
    source = json.loads((root / "sysdig-native-mutations-source.json").read_text())
    raw = (root / "sysdig-native-mutations.jsonl").read_bytes()
    assert digest(raw) == source["fixture_sha256"]
    result = parse_sysdig(raw.decode(), container_id=source["container_id"])
    prefix = "/sandbox/fixed-trace-probe/"
    assert not result.unresolved_events
    assert not result.envelope.files_read
    assert result.envelope.files_written == {prefix + name for name in (
        "exclusive-empty.txt", "existing-create.txt", "truncated.txt", "rename-source.txt",
        "rename-target.txt", "hardlink.txt", "symlink.txt", "removed.txt", "removed-directory")}
    assert result.path_mutation_capabilities.files_written == {prefix + "existing-create.txt"}
    symlink = next(m for m in result.file_mutations if m["kind"] == "symlinkat")
    assert symlink["paths"] == [prefix + "symlink.txt"]
    assert {m["action"] for m in result.file_mutations} >= {
        "exclusive_create", "possible_create", "open_truncate", "rename", "link",
        "symlink", "unlink", "mkdir", "rmdir"}
    assert result.complete is False


def test_native_directory_tmpfile_flag_ambiguity_is_not_treated_as_creation():
    from pathlib import Path

    from skillguard.review.snapshot import digest

    root = Path(__file__).parent / "fixtures"
    source = json.loads((root / "sysdig-native-directory-open-source.json").read_text())
    raw = (root / "sysdig-native-directory-open.jsonl").read_bytes()
    assert digest(raw) == source["fixture_sha256"]
    result = parse_sysdig(raw.decode(), container_id=source["container_id"])
    assert not result.envelope.files_written
    assert not result.path_mutation_capabilities.files_written
    assert not result.file_mutations
    assert result.unresolved_events == {}
    assert result.directory_opens == [{
        'path': '/usr/local/lib/python3.12', 'kind': 'openat', 'descriptor': 3,
        'exit_ref': 'sysdig:202286', 'native_tmpfile_flag_conflict': True,
        'byte_access_observed': False}]


@pytest.mark.parametrize('fault', ['type', 'descriptor', 'path', 'write', 'create', 'truncate',
                                 'unknown_flag', 'unknown_path'])
def test_directory_flag_conflict_cannot_hide_a_file_or_mutating_open(fault):
    from pathlib import Path

    value = json.loads((Path(__file__).parent / 'fixtures/'
                       'sysdig-native-directory-open.jsonl').read_text())
    if fault == 'type':
        value['fd.type'] = 'file'
    elif fault == 'descriptor':
        value['evt.arg.fd'] = '<f>/usr/local/lib/python3.12'
    elif fault == 'path':
        value['fs.path.name'] = '/different'
    elif fault == 'unknown_path':
        value['fd.name'] = '<UNKNOWN>/usr/local/lib/python3.12'
    else:
        value['evt.arg.flags'] += '|' + {'write': 'O_RDWR', 'create': 'O_CREAT',
            'truncate': 'O_TRUNC', 'unknown_flag': 'UNRECOGNIZED_FLAG'}[fault]
    result = parse_sysdig(json.dumps(value), container_id=value['container.full_id'])
    assert result.unresolved_events and not result.directory_opens


@pytest.mark.parametrize("kind", ["chmod", "fchmodat", "chown", "lchown", "fchownat"])
def test_successful_native_path_metadata_change_is_a_write_without_content_io(kind):
    e = event(kind, **{"fs.path.name": "/sandbox/metadata-target",
                       "evt.arg.mode": "0640", "evt.arg.uid": "1000", "evt.arg.gid": "1000"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert result.envelope.files_written == {"/sandbox/metadata-target"}
    assert not result.envelope.files_read
    assert result.file_mutations[0]["action"] == (
        "permissions" if "chmod" in kind else "ownership")
    assert result.file_mutations[0]["actual_mutation"] is True
    assert result.complete is False


@pytest.mark.parametrize("kind", ["fchmod", "fchown"])
def test_descriptor_metadata_change_uses_native_file_identity_not_unrelated_path(kind):
    e = event(kind, **{"fd.type": "file", "fd.name": "/sandbox/open-file",
                       "fs.path.name": "/unrelated", "evt.arg.mode": "0600",
                       "evt.arg.uid": "1000", "evt.arg.gid": "1000"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert result.envelope.files_written == {"/sandbox/open-file"}


@pytest.mark.parametrize("fields", [
    {"fd.type": "file", "fd.name": "<UNKNOWN>/file"},
    {"fd.type": "ipv4", "fd.name": "/not-a-file"},
    {"fd.type": None, "fd.name": None},
])
def test_unresolved_descriptor_metadata_remains_a_gap(fields):
    e = event("fchmod", **(fields | {"evt.arg.mode": "0600"}))
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert not result.file_mutations
    assert result.unresolved_events


@pytest.mark.parametrize("kind", ["chmod", "fchmod", "chown", "fchown"])
def test_denied_metadata_change_cannot_claim_a_write(kind):
    e = event(kind, **{"evt.rawres": -1, "fs.path.name": "/sandbox/file"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert not result.file_mutations
    assert not result.unresolved_events


def test_generic_fchmodat2_without_outcome_stays_unresolved():
    e = event("fchmodat2", **{"evt.rawres": None, "fs.path.name": "/sandbox/file"})
    result = parse_sysdig(json.dumps(e), container_id=CONTAINER)
    assert not result.file_mutations
    assert result.unresolved_events


def test_actual_native_metadata_paths_and_values_keep_follow_flag_gap():
    from pathlib import Path

    from skillguard.review.snapshot import digest

    root = Path(__file__).parent / "fixtures"
    source = json.loads((root / "sysdig-native-file-metadata-source.json").read_text())
    raw = (root / "sysdig-native-file-metadata.jsonl").read_bytes()
    assert digest(raw) == source["fixture_sha256"]
    result = parse_sysdig(raw.decode(), container_id=source["container_id"])
    assert len(result.file_mutations) == 5
    assert result.envelope.files_written == {
        "/sandbox/fixed-trace-probe/metadata-file.txt", "/sandbox/fixed-trace-probe/symlink.txt"}
    assert not result.envelope.files_read
    assert result.file_mutations[0]["requested_metadata"]["mode"] == "S_IRGRP|S_IWUSR|S_IRUSR"
    assert result.file_mutations[2]["requested_metadata"] == {"uid": "1000", "gid": "1000"}
    assert set(result.unresolved_events) == {"sysdig:347087", "sysdig:347234"}
    assert result.complete is False
