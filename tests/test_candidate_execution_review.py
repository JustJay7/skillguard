import json
from pathlib import Path

import pytest

from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore
from tests.test_pending import batch_record


def fixture(tmp_path, *, functional=False):
    source = tmp_path / "pending.json"
    source.write_text(json.dumps(batch_record(path="scripts/parse_receipt.py")))
    store = ReviewStore(tmp_path / "reviews")
    rid = store.capture(source)
    review = store.get(rid)
    event = json.loads(Path("tests/fixtures/sysdig-fixed-probe.jsonl").read_text().splitlines()[0])
    rows = []
    for num, (kind, path) in enumerate(
        [
            ("read", "/opt/skillguard-candidate/scripts/parse_receipt.py"),
            ("read", "/opt/skillguard-fixtures/input.txt"),
            ("write", "/sandbox/receipt-output.json"),
        ],
        1,
    ):
        rows.append(
            event
            | {
                "evt.num": num,
                "evt.type": kind,
                "evt.rawres": 10,
                "fd.type": "file",
                "fd.name": path,
            }
        )
    image = "sha256:" + "a" * 64
    candidate = {
        "candidate_sha256": review["candidate_sha256"],
        "parser_sha256": digest(
            (Path(review["snapshot"]) / "scripts/parse_receipt.py").read_bytes()
        ),
        "functional_passed": functional,
        "source_hashes_match": True,
        "mismatched_fields": [] if functional else ["total"],
    }
    artifacts = {
        "candidate-image.json": json.dumps(
            {"source_sha256": review["candidate_sha256"], "image_id": image}
        ).encode(),
        "candidate-execution.json": b"{}",
        "container.json": json.dumps({"id": event["container.full_id"], "image": image}).encode(),
        "native-sandbox.json": b"{}",
        "capture-stats.txt": (b"Driver Events:10\nDriver Drops:0\n"
                              b"Suppressed by Comm:0\nCaptured Events: 10"),
        "workload.jsonl": "\n".join(json.dumps(row) for row in rows).encode(),
    }
    report = {
        "scope": "known_learned_candidate_probe",
        "complete": False,
        "activation_eligible": False,
        "candidate_execution": candidate,
        "collector_active_after_probe": True,
        "coverage_markers_passed": True,
        "artifacts": {name: digest(raw) for name, raw in artifacts.items()},
    }
    return store, rid, report, artifacts


def test_static_pass_cannot_approve_candidate_that_fails_native_functional_check(tmp_path):
    store, rid, report, artifacts = fixture(tmp_path)
    store.record_static(rid, {"overall_status": "passed", "incomplete_scans": []})
    event = store.record_candidate_execution_probe(
        rid, report=json.dumps(report).encode(), artifacts=artifacts
    )
    reopened = ReviewStore(store.root)
    decision = reopened.decide(rid)
    assert "Native candidate functional check failed" in decision["reasons"]
    assert decision["activation_permitted"] is False
    assert event["data"]["functional_passed"] is False
    assert reopened.evidence(rid)["E8"]["value"]["mismatched_fields"] == ["total"]
    assert "partial" in reopened.evidence(rid)["E2"]["value"]
    assert "replay" not in reopened.get(rid)["latest"]


def test_successful_bounded_candidate_probe_still_cannot_grant_completeness(tmp_path):
    store, rid, report, artifacts = fixture(tmp_path, functional=True)
    store.record_candidate_execution_probe(
        rid, report=json.dumps(report).encode(), artifacts=artifacts
    )
    assert store.get(rid)["latest"]["candidate_execution"]["complete"] is False
    assert store.decide(rid)["activation_permitted"] is False


def test_execution_identity_must_match_reviewed_candidate_and_native_image(tmp_path):
    store, rid, report, artifacts = fixture(tmp_path)
    report["candidate_execution"]["candidate_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="identity"):
        store.record_candidate_execution_probe(
            rid, report=json.dumps(report).encode(), artifacts=artifacts
        )
    assert "candidate_execution" not in store.get(rid)["latest"]


def test_changed_native_artifact_cannot_receive_execution_review(tmp_path):
    store, rid, report, artifacts = fixture(tmp_path)
    artifacts["candidate-execution.json"] = b"changed"
    with pytest.raises(ValueError, match="hash"):
        store.record_candidate_execution_probe(
            rid, report=json.dumps(report).encode(), artifacts=artifacts
        )
