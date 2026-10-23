import json
from pathlib import Path

from skillguard.review.snapshot import digest
from skillguard.traces.sysdig import parse_sysdig


def test_actual_native_mapping_and_copy_metadata_keeps_permission_and_byte_facts_separate():
    root = Path(__file__).parent / "fixtures"
    source = json.loads((root / "sysdig-native-access-source.json").read_text())
    fixture = (root / "sysdig-native-access.jsonl").read_bytes()
    assert digest(fixture) == source["fixture_sha256"]
    evidence = parse_sysdig(fixture.decode(), container_id=source["container_id"])
    prefix = "/sandbox/fixed-trace-probe/"
    assert evidence.envelope.files_read == {prefix + "transfer-source.txt"}
    assert evidence.envelope.files_written == {
        prefix + kind + "-output.txt" for kind in ("sendfile", "copy_file_range", "splice")}
    assert evidence.mapping_capabilities.files_read == {
        prefix + "mapped-" + mode + ".txt" for mode in ("read", "private", "shared")}
    assert evidence.mapping_capabilities.files_written == {prefix + "mapped-shared.txt"}
    assert len(evidence.file_transfers) == 4
    assert len(evidence.memory_mappings) == 3
    assert len(evidence.unresolved_events) == 2  # unresolved pipe endpoints of splice
    assert all("descriptor" in reason for reason in evidence.unresolved_events.values())
    assert all(not m["page_access_observed"] for m in evidence.memory_mappings)
    assert evidence.complete is False
