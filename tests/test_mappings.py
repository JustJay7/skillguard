import hashlib
import json
from pathlib import Path

import pytest

from skillguard.traces.sysdig import parse_sysdig
from tests.test_process_scope import CONTAINER, row


def mapping(*, fd="<f>/fake/input.txt", flags="MAP_PRIVATE", prot="PROT_READ", result=8192):
    start = row(1, 20, 200, "mmap") | {
        "evt.dir": ">", "evt.rawres": None, "fd.type": None, "fd.name": None,
        "evt.arg.fd": fd, "evt.arg.flags": flags, "evt.arg.prot": prot,
    }
    end = row(2, 20, 200, "mmap") | {
        "evt.rawres": result, "fd.type": None, "fd.name": None,
        "evt.arg.fd": None, "evt.arg.flags": None, "evt.arg.prot": None,
    }
    return [start, end]


def parse(rows):
    return parse_sysdig("\n".join(json.dumps(r) for r in rows), container_id=CONTAINER)


def test_native_readable_file_mapping_is_separate_from_completed_byte_reads():
    evidence = parse(mapping())
    assert evidence.envelope.files_read == set()
    assert evidence.mapping_capabilities.files_read == {"/fake/input.txt"}
    assert evidence.memory_mappings[0]["entry_ref"] == "sysdig:1"
    assert evidence.memory_mappings[0]["exit_ref"] == "sysdig:2"
    assert evidence.unresolved_events == {}
    assert evidence.complete is False


@pytest.mark.parametrize("flags,writable", [("MAP_PRIVATE", False), ("MAP_SHARED", True)])
def test_writable_private_mapping_does_not_claim_file_write(flags, writable):
    evidence = parse(mapping(flags=flags, prot="PROT_READ|PROT_WRITE"))
    assert evidence.envelope.files_written == set()
    assert bool(evidence.mapping_capabilities.files_written) is writable
    assert evidence.memory_mappings[0]["writable"] is True


def test_anonymous_mapping_fd_minus_one_formatter_is_not_a_failed_operation():
    evidence = parse(mapping(fd="EPERM", flags="MAP_PRIVATE|MAP_ANONYMOUS"))
    assert evidence.anonymous_mappings == 1
    assert evidence.memory_mappings == []
    assert evidence.unresolved_events == {}


def test_failed_mapping_adds_no_access_fact():
    evidence = parse(mapping(result=-13))
    assert evidence.memory_mappings == []
    assert evidence.mapping_capabilities.files_read == set()
    assert evidence.unresolved_events == {}


@pytest.mark.parametrize("field", ["thread.tid", "proc.pid.ts"])
def test_pid_or_thread_identity_mismatch_cannot_pair_native_mapping(field):
    rows = mapping()
    rows[1][field] += 1
    evidence = parse(rows)
    assert evidence.memory_mappings == []
    assert evidence.unresolved_events


def test_thread_exit_clears_pending_mapping_before_tid_reuse():
    rows = mapping()
    exit_row = row(2, 20, 200, "procexit")
    rows[1]["evt.num"] = 3
    evidence = parse([rows[0], exit_row, rows[1]])
    assert evidence.memory_mappings == []
    assert evidence.unresolved_events


def test_interleaved_threads_pair_their_own_descriptor_metadata():
    first, second = mapping(), mapping(fd="<f>/fake/other.txt")
    second[0].update({"evt.num": 2, "thread.tid": 21})
    second[1].update({"evt.num": 3, "thread.tid": 21})
    first[1]["evt.num"] = 4
    evidence = parse([first[0], *second, first[1]])
    assert evidence.mapping_capabilities.files_read == {"/fake/input.txt", "/fake/other.txt"}
    assert [(r["entry_ref"], r["exit_ref"]) for r in evidence.memory_mappings] == [
        ("sysdig:2", "sysdig:3"), ("sysdig:1", "sysdig:4")]


def test_duplicate_nested_mapping_entry_remains_ambiguous():
    rows = mapping()
    repeated = rows[0] | {"evt.num": 2}
    rows[1]["evt.num"] = 3
    evidence = parse([rows[0], repeated, rows[1]])
    assert evidence.memory_mappings == []
    assert evidence.unresolved_events


@pytest.mark.parametrize("fd", [None, "<f><UNKNOWN>root/file", "<f>relative", "<s>socket"])
def test_unresolved_file_descriptor_never_becomes_a_path(fd):
    evidence = parse(mapping(fd=fd))
    assert evidence.memory_mappings == []
    assert evidence.unresolved_events


def test_reversed_mapping_completion_order_cannot_add_capability():
    rows = mapping()
    evidence = parse(list(reversed(rows)))
    assert evidence.memory_mappings == []
    assert evidence.unresolved_events


def test_unknown_protection_bits_remain_an_explicit_gap():
    evidence = parse(mapping(prot="PROT_READ|UNRECOGNIZED"))
    assert evidence.memory_mappings == []
    assert evidence.unresolved_events


def mapping_change(kind="mprotect", result=0):
    start = row(3, 20, 200, kind) | {
        "evt.dir": ">", "evt.rawres": None, "evt.arg.addr": "2000",
        "evt.arg.length": "4096", "evt.arg.prot": "PROT_READ|PROT_WRITE",
    }
    end = row(4, 20, 200, kind) | {"evt.rawres": result}
    return [start, end]


def test_write_permission_added_to_initially_read_only_map_is_not_silently_ignored():
    evidence = parse(mapping(flags="MAP_SHARED") + mapping_change())
    assert evidence.mapping_changes[0]["protection"] == "PROT_READ|PROT_WRITE"
    assert evidence.mapping_changes[0]["entry_ref"] == "sysdig:3"
    assert evidence.mapping_changes[0]["exit_ref"] == "sysdig:4"
    assert evidence.mapping_changes[0]["backing_file"] is None
    assert "sysdig:4" in evidence.unresolved_events
    assert evidence.envelope.files_written == set()
    assert evidence.complete is False


@pytest.mark.parametrize("kind", ["mprotect", "munmap"])
def test_completed_lifecycle_change_requires_observed_pair_and_remains_a_gap(kind):
    evidence = parse(mapping_change(kind))
    assert evidence.mapping_changes[0]["kind"] == kind
    assert evidence.unresolved_events
    unpaired = parse(mapping_change(kind)[1:])
    assert unpaired.mapping_changes == []
    assert unpaired.unresolved_events


@pytest.mark.parametrize("kind", ["mprotect", "munmap"])
def test_denied_lifecycle_change_cannot_claim_a_permission_or_lifetime_change(kind):
    evidence = parse(mapping_change(kind, result=-13))
    assert evidence.mapping_changes == []
    assert evidence.unresolved_events == {}


@pytest.mark.parametrize("kind", ["mremap", "pkey_mprotect"])
def test_generic_native_mapping_events_cannot_be_interpreted_as_denials(kind):
    evidence = parse([row(1, 20, 200, kind) | {"evt.rawres": None}])
    assert evidence.mapping_changes == []
    assert "lacks mapping arguments/outcome" in evidence.unresolved_events["sysdig:1"]


def test_mapping_change_thread_exit_or_identity_mismatch_never_pairs():
    start, end = mapping_change()
    end["thread.tid"] += 1
    evidence = parse([start, row(4, 20, 200, "procexit"), end | {"evt.num": 5}])
    assert evidence.mapping_changes == []
    assert evidence.unresolved_events


def test_actual_native_permission_upgrade_and_removal_keep_unresolved_backing_ranges():
    directory = Path(__file__).parent / "fixtures"
    raw = (directory / "sysdig-native-mapping-changes.jsonl").read_bytes()
    source = json.loads((directory / "sysdig-native-mapping-changes-source.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == source["fixture_sha256"]
    evidence = parse_sysdig(raw.decode(), container_id=source["container_id"])
    assert len(evidence.memory_mappings) == 1
    assert evidence.memory_mappings[0]["shared"] is True
    assert evidence.memory_mappings[0]["writable"] is False
    assert [m["kind"] for m in evidence.mapping_changes] == ["mprotect", "munmap"]
    assert evidence.mapping_changes[0]["protection"] == "PROT_READ|PROT_WRITE"
    assert set(evidence.unresolved_events) == {"sysdig:343403", "sysdig:343692"}
    assert evidence.envelope.files_written == set()
    assert evidence.complete is False
