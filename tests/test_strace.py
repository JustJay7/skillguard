from pathlib import Path

from skillguard.traces.strace import parse_strace


def test_parse_strace_builds_behavioral_envelope() -> None:
    trace = Path("tests/fixtures/strace_planted.txt").read_text()

    envelope = parse_strace(trace)

    assert envelope.files_read == frozenset({"/tmp/invoice.txt", "/tmp/private.txt"})
    assert envelope.files_written == frozenset({"/tmp/out.json"})
    assert envelope.network_hosts == frozenset({"127.0.0.1:8765"})
    assert envelope.processes == frozenset({"/usr/bin/python3", "/usr/bin/curl"})
