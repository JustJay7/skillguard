import json

import pytest

from skillguard.traces.sysdig import parse_sysdig
from tests.test_process_scope import CONTAINER, row


def transfer(kind="sendfile", *, source="<f>/fake/input", target="<f>/fake/output", result=16):
    keys = {"sendfile": ("in_fd", "out_fd"), "splice": ("fd_in", "fd_out"),
            "copy_file_range": ("fdin", "fdout")}
    incoming, outgoing = keys[kind]
    start = row(1, 20, 200, kind) | {"evt.dir": ">", "evt.rawres": None,
                                       "fd.type": None, "fd.name": None,
                                       "evt.arg." + incoming: source}
    end = row(2, 20, 200, kind) | {"evt.rawres": result, "fd.type": None, "fd.name": None}
    (end if kind == "copy_file_range" else start)["evt.arg." + outgoing] = target
    return [start, end]


def parse(rows):
    return parse_sysdig("\n".join(json.dumps(r) for r in rows), container_id=CONTAINER)


@pytest.mark.parametrize("kind", ["sendfile", "copy_file_range"])
def test_completed_native_file_copy_proves_read_and_write_without_ordinary_io(kind):
    evidence = parse(transfer(kind))
    assert evidence.envelope.files_read == {"/fake/input"}
    assert evidence.envelope.files_written == {"/fake/output"}
    assert evidence.event_refs["files_written:/fake/output"] == ["sysdig:2"]
    assert evidence.file_transfers[0]["bytes_transferred"] == 16
    assert evidence.unresolved_events == {}
    assert evidence.complete is False


@pytest.mark.parametrize("result", [0, -13])
def test_eof_and_failed_copy_prove_no_completed_file_access(result):
    evidence = parse(transfer(result=result))
    assert evidence.envelope.files_read == set()
    assert evidence.envelope.files_written == set()
    assert evidence.unresolved_events == {}


def test_splice_file_to_pipe_keeps_file_read_and_unresolved_peer():
    evidence = parse(transfer("splice", target="<p>pipe"))
    assert evidence.envelope.files_read == {"/fake/input"}
    assert evidence.envelope.files_written == set()
    assert evidence.unresolved_events


def test_splice_pipe_to_file_keeps_file_write_and_unresolved_peer():
    evidence = parse(transfer("splice", source="<p>pipe"))
    assert evidence.envelope.files_read == set()
    assert evidence.envelope.files_written == {"/fake/output"}
    assert evidence.unresolved_events


@pytest.mark.parametrize("field", ["thread.tid", "proc.pid.ts"])
def test_different_thread_or_reused_process_cannot_supply_copy_source(field):
    rows = transfer()
    rows[1][field] += 1
    evidence = parse(rows)
    assert evidence.envelope.files_read == set()
    assert evidence.unresolved_events


def test_missing_entry_cannot_turn_native_copy_into_an_empty_safe_trace():
    evidence = parse(transfer()[1:])
    assert evidence.file_transfers == []
    assert evidence.unresolved_events


def test_duplicate_nested_copy_entry_never_produces_a_file_access_fact():
    rows = transfer()
    extra = rows[0] | {"evt.num": 2}
    rows[1]["evt.num"] = 3
    evidence = parse([rows[0], extra, rows[1]])
    assert evidence.file_transfers == []
    assert evidence.unresolved_events


def test_thread_exit_clears_copy_source_before_tid_reuse():
    rows = transfer()
    rows[1]["evt.num"] = 3
    evidence = parse([rows[0], row(2, 20, 200, "procexit"), rows[1]])
    assert evidence.envelope.files_written == set()
    assert evidence.unresolved_events
