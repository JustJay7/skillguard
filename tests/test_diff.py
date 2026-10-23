from skillguard.envelope.diff import diff_envelopes
from skillguard.envelope.schema import BehavioralEnvelope


def test_behavioral_diff_reports_added_and_removed_capabilities() -> None:
    before = BehavioralEnvelope(
        files_read={"/tmp/invoice.txt"},
        processes={"python3"},
    )
    after = BehavioralEnvelope(
        files_read={"/tmp/invoice.txt", "/tmp/private.txt"},
        network_hosts={"127.0.0.1:8765"},
        processes={"python3", "curl"},
    )

    result = diff_envelopes(before, after)

    assert result.added.files_read == frozenset({"/tmp/private.txt"})
    assert result.added.network_hosts == frozenset({"127.0.0.1:8765"})
    assert result.added.processes == frozenset({"curl"})
    assert result.removed == BehavioralEnvelope()


def test_diff_is_empty_for_identical_envelopes() -> None:
    envelope = BehavioralEnvelope(files_read={"/tmp/invoice.txt"})
    result = diff_envelopes(envelope, envelope)

    assert result.is_empty
