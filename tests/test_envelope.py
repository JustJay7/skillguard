from skillguard.envelope.schema import BehavioralEnvelope


def test_envelope_normalizes_and_serializes_deterministically() -> None:
    envelope = BehavioralEnvelope(
        files_read={"/tmp/b", "/tmp/a"},
        files_written={"/tmp/out"},
        network_hosts={"127.0.0.1:8765"},
        processes={"curl", "python3"},
        tools={"read_file"},
    )

    assert envelope.to_dict() == {
        "files_read": ["/tmp/a", "/tmp/b"],
        "files_written": ["/tmp/out"],
        "network_hosts": ["127.0.0.1:8765"],
        "processes": ["curl", "python3"],
        "tools": ["read_file"],
    }


def test_envelope_round_trips_from_dict() -> None:
    payload = {
        "files_read": ["/tmp/invoice.txt"],
        "files_written": [],
        "network_hosts": [],
        "processes": ["python3"],
        "tools": [],
    }

    assert BehavioralEnvelope.from_dict(payload).to_dict() == payload
