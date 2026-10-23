import json
from pathlib import Path

import pytest

from skillguard.traces.sysdig import SYSDIG_FORMAT, parse_sysdig, parse_sysdig_stats

FIXTURE = Path(__file__).parent / "fixtures/sysdig-fixed-probe.jsonl"
CONTAINER = "05ea224b34a303ca46600f9fd4b61d7728c19ff530205e9c2df4bd218a78a9fd"


def rows():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines()]


def test_actual_kernel_capture_contains_untraced_child_and_completed_io():
    evidence = parse_sysdig(FIXTURE.read_text(), container_id=CONTAINER)
    assert "/sandbox/fixed-trace-probe/receipt.txt" in evidence.envelope.files_read
    assert "/sandbox/fixed-trace-probe/output.txt" in evidence.envelope.files_written
    marker = "/sandbox/fixed-trace-probe/untraced-marker.txt"
    assert marker in evidence.envelope.files_written
    assert evidence.event_refs[f"files_written:{marker}"] == ["sysdig:621311"]
    assert "/usr/bin/echo" in evidence.envelope.processes
    assert evidence.envelope.network_hosts == {"127.0.0.1:38945"}
    assert evidence.unresolved_events == {"sysdig:620722": "connect destination unresolved"}
    assert evidence.complete is False
    assert SYSDIG_FORMAT.startswith("*")


@pytest.mark.parametrize("return_value", [-13, 0])
def test_failed_reads_and_eof_do_not_become_completed_reads(return_value):
    event = next(row for row in rows() if row["evt.type"] == "read")
    event["evt.rawres"] = return_value
    result = parse_sysdig(json.dumps(event), container_id=CONTAINER)
    assert result.envelope.files_read == set()


def test_entry_events_do_not_claim_execution_or_io():
    event = next(row for row in rows() if row["evt.type"] == "execve")
    event.update({"evt.dir": ">", "evt.rawres": None})
    result = parse_sysdig(json.dumps(event), container_id=CONTAINER)
    assert result.envelope.processes == set()


def test_successful_native_mmap_remains_an_explicit_access_gap():
    event = rows()[0]
    event.update({"evt.type": "mmap", "evt.dir": "<", "evt.rawres": 123456,
                  "fd.type": None, "fd.name": None})
    result = parse_sysdig(json.dumps(event), container_id=CONTAINER)
    assert result.envelope.files_read == set()
    assert "mmap access not represented" in result.unresolved_events[f"sysdig:{event['evt.num']}"]
    assert result.complete is False


@pytest.mark.parametrize("direction,result", [(">", None), ("<", -13)])
def test_entry_or_failed_mmap_cannot_add_access_fact(direction, result):
    event = rows()[0]
    event.update({"evt.type": "mmap", "evt.dir": direction, "evt.rawres": result})
    evidence = parse_sysdig(json.dumps(event), container_id=CONTAINER)
    assert evidence.mapping_capabilities.files_read == set()
    if direction == "<":
        assert evidence.unresolved_events == {}
    else:
        assert evidence.unresolved_events  # incomplete legacy entry metadata


@pytest.mark.parametrize("kind", ["sendfile", "splice", "copy_file_range"])
def test_successful_zero_copy_io_cannot_silently_look_like_no_access(kind):
    event = rows()[0]
    event.update({"evt.type": kind, "evt.dir": "<", "evt.rawres": 12})
    evidence = parse_sysdig(json.dumps(event), container_id=CONTAINER)
    assert "access not represented" in evidence.unresolved_events[f"sysdig:{event['evt.num']}"]
    event["evt.rawres"] = 0
    assert parse_sysdig(json.dumps(event), container_id=CONTAINER).unresolved_events == {}


@pytest.mark.parametrize("kind", ["mmap2", "io_uring_setup", "io_uring_enter", "io_uring_register"])
def test_successful_mapping_or_async_setup_remains_partial(kind):
    event = rows()[0]
    event.update({"evt.type": kind, "evt.dir": "<", "evt.rawres": 0})
    evidence = parse_sysdig(json.dumps(event), container_id=CONTAINER)
    assert evidence.unresolved_events
    assert evidence.complete is False


@pytest.mark.parametrize("full_id", [None, "0" * 64])
def test_truncated_id_cannot_substitute_for_exact_binding(full_id):
    event = rows()[0]
    event["container.full_id"] = full_id
    with pytest.raises(ValueError, match="exact native container identity"):
        parse_sysdig(json.dumps(event), container_id=CONTAINER)


def test_foreign_container_events_cannot_pollute_target_envelope():
    event = rows()[0]
    event.update({"container.id": "foreign", "container.full_id": "f" * 64})
    result = parse_sysdig(json.dumps(event) + "\n" + FIXTURE.read_text(), container_id=CONTAINER)
    assert result.scoped_events == len(rows())


@pytest.mark.parametrize("field,value", [("evt.rawres", None), ("evt.rawres", True),
                                        ("fd.name", "relative.txt")])
def test_unresolved_completed_file_metadata_fails_closed(field, value):
    event = next(row for row in rows() if row["evt.type"] == "write")
    event[field] = value
    with pytest.raises(ValueError):
        parse_sysdig(json.dumps(event), container_id=CONTAINER)


def test_duplicate_scoped_events_are_rejected():
    event = json.dumps(rows()[0])
    with pytest.raises(ValueError, match="duplicate"):
        parse_sysdig(event + "\n" + event, container_id=CONTAINER)


def test_native_unknown_root_file_path_remains_an_explicit_gap():
    event = next(row for row in rows() if row["evt.type"] == "write")
    event["fd.name"] = "<UNKNOWN>thread-self/fd/8"
    result = parse_sysdig(json.dumps(event), container_id=CONTAINER)
    assert result.envelope.files_written == set()
    assert result.unresolved_events == {
        f"sysdig:{event['evt.num']}": "native file path root unresolved"
    }
    assert result.complete is False


def test_missing_target_events_are_not_an_empty_success():
    with pytest.raises(ValueError, match="No events"):
        parse_sysdig("", container_id=CONTAINER)


def test_invalid_event_stream_is_not_partially_accepted():
    with pytest.raises(ValueError, match="Invalid native JSON"):
        parse_sysdig(FIXTURE.read_text() + "{", container_id=CONTAINER)


def test_native_container_metadata_is_not_a_process_execution():
    event = rows()[0]
    event.update({"evt.type": "container", "evt.dir": ">", "evt.rawres": None,
                  "proc.pid": None, "proc.exepath": None})
    result = parse_sysdig(json.dumps(event), container_id=CONTAINER)
    assert result.envelope.processes == set()
    assert result.complete is False


def test_teardown_identity_loss_is_explicit_and_never_a_behavior_fact():
    event = rows()[0]
    event.update({"evt.type": "procexit", "container.full_id": None})
    result = parse_sysdig(json.dumps(event) + "\n" + json.dumps(rows()[1]), container_id=CONTAINER)
    assert result.unresolved_events == {
        f"sysdig:{event['evt.num']}": "unbound native metadata event"
    }
    assert result.complete is False


def test_native_drop_counter_is_retained_and_never_grants_completeness():
    stats = parse_sysdig_stats(
        "Driver Events:12\nDriver Drops:3\nSuppressed by Comm:0\nCaptured Events: 9"
    )
    assert stats["driver_drops"] == 3
    assert parse_sysdig(FIXTURE.read_text(), container_id=CONTAINER).complete is False


@pytest.mark.parametrize("text", ["Driver Drops:0", ""])
def test_zero_drop_statement_without_complete_native_stats_is_rejected(text):
    with pytest.raises(ValueError, match="capture counter"):
        parse_sysdig_stats(text)
