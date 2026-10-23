import hashlib
import json
from pathlib import Path

import pytest

from skillguard.cli import main
from skillguard.review.store import ReviewStore
from skillguard.traces.sysdig import capture_failures
from tests.test_review_store import pending


def probe_artifacts(**changes):
    artifacts = {
        name: b"fixed test metadata"
        for name in (
            "raw-events.jsonl",
            "capture-stats.txt",
            "probe-console.json",
            "container.json",
            "fixed-probe.py",
            "native-sandbox.json",
        )
    }
    report = {
        "scope": "fixed_fake_data_probe",
        "complete": False,
        "activation_eligible": False,
        "collector_active_after_probe": False,
        "coverage_markers_passed": False,
        "native_stats": None,
        "workload_checks": {"functional_passed": True},
        "artifacts": {key: hashlib.sha256(value).hexdigest() for key, value in artifacts.items()},
    } | changes
    return json.dumps(report).encode(), artifacts


def test_task_success_does_not_mask_lost_collector(tmp_path: Path):
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    store.record_static(review_id, {"overall_status": "passed", "incomplete_scans": []})
    raw, artifacts = probe_artifacts()
    store.record_capture_probe(review_id, report=raw, artifacts=artifacts)
    response = json.loads(Path("tests/fixtures/nemotron_receipt_response.json").read_text())
    advice = json.loads(response["choices"][0]["message"]["content"])
    advice["recommendation"] = "allow"
    store.record_advice(review_id, json.dumps(advice), source="recorded")
    reopened = ReviewStore(tmp_path / "reviews")
    event = reopened.get(review_id)["latest"]["capture_probe"]
    assert event["functional_passed"] is True
    assert event["candidate_executed"] is False
    assert "replay" not in reopened.get(review_id)["latest"]
    decision = reopened.decide(review_id)
    assert decision["decision"] == "held"
    assert decision["activation_permitted"] is False
    assert any("collector stopped" in reason for reason in decision["reasons"])
    assert reopened.evidence(review_id)["E7"]["value"]["complete"] is False


def test_capture_probe_requires_unchanged_raw_artifacts(tmp_path: Path):
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    raw, artifacts = probe_artifacts()
    artifacts["capture-stats.txt"] = b"changed"
    with pytest.raises(ValueError, match="hash"):
        store.record_capture_probe(review_id, report=raw, artifacts=artifacts)
    assert "capture_probe" not in store.get(review_id)["latest"]


def test_capture_probe_cannot_claim_candidate_completeness(tmp_path: Path):
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    raw, artifacts = probe_artifacts(complete=True)
    with pytest.raises(ValueError, match="bounded"):
        store.record_capture_probe(review_id, report=raw, artifacts=artifacts)


def test_cli_archives_native_report_without_promoting_it_to_replay(tmp_path: Path, capsys):
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    raw, artifacts = probe_artifacts()
    report = tmp_path / "backend.json"
    report.write_bytes(raw)
    for name, data in artifacts.items():
        (tmp_path / name).write_bytes(data)
    assert main(["capture-probe", review_id, "--store", str(store.root),
                 "--report", str(report)]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["candidate_executed"] is False
    assert store.decide(review_id)["activation_permitted"] is False


def test_corrupt_archived_capture_cannot_receive_a_decision(tmp_path: Path):
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    raw, artifacts = probe_artifacts()
    event = store.record_capture_probe(review_id, report=raw, artifacts=artifacts)
    Path(event["data"]["attachments"][0]["artifact"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="artifact changed"):
        store.decide(review_id)


def test_new_capture_invalidates_old_model_advice(tmp_path: Path):
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    response = json.loads(Path("tests/fixtures/nemotron_receipt_response.json").read_text())
    store.record_advice(review_id, response["choices"][0]["message"]["content"], source="recorded")
    raw, artifacts = probe_artifacts()
    store.record_capture_probe(review_id, report=raw, artifacts=artifacts)
    assert "Model advice refers to an older evidence revision" in store.decide(review_id)["reasons"]


@pytest.mark.parametrize("name", ["../outside-file", "/tmp/outside-file"])
def test_cli_rejects_artifact_paths_outside_report_directory(tmp_path: Path, name: str):
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    raw, _ = probe_artifacts(artifacts={name: "unused"})
    report = tmp_path / "backend.json"
    report.write_bytes(raw)
    with pytest.raises(ValueError, match="local filename"):
        main(["capture-probe", review_id, "--store", str(store.root), "--report", str(report)])


@pytest.mark.parametrize(
    "stats, active, coverage",
    [
        (None, True, True),
        (
            {"driver_events": 10, "captured_events": 10, "driver_drops": 1, "suppressed_comm": 0},
            True,
            True,
        ),
        (
            {"driver_events": 10, "captured_events": 10, "driver_drops": 0, "suppressed_comm": 1},
            True,
            True,
        ),
        (
            {"driver_events": 10, "captured_events": 10, "driver_drops": 0, "suppressed_comm": 0},
            False,
            True,
        ),
        (
            {"driver_events": 0, "captured_events": 0, "driver_drops": 0, "suppressed_comm": 0},
            True,
            True,
        ),
        (
            {"driver_events": 10, "captured_events": 10, "driver_drops": 0, "suppressed_comm": 0},
            True,
            False,
        ),
        (
            {"driver_events": True, "captured_events": 10, "driver_drops": 0, "suppressed_comm": 0},
            True,
            True,
        ),
    ],
)
def test_native_failure_fields_fail_closed(stats, active, coverage):
    assert capture_failures(active=active, stats=stats, coverage=coverage)


def test_healthy_fixed_probe_is_not_complete_candidate_evidence(tmp_path: Path):
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    raw, artifacts = probe_artifacts(
        collector_active_after_probe=True,
        coverage_markers_passed=True,
        native_stats={
            "driver_events": 10,
            "captured_events": 10,
            "driver_drops": 0,
            "suppressed_comm": 0,
        },
    )
    event = store.record_capture_probe(review_id, report=raw, artifacts=artifacts)["data"]
    assert event["failure_reasons"] == []
    assert event["complete"] is False
    assert store.decide(review_id)["activation_permitted"] is False
