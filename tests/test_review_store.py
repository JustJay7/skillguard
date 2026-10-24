import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.intercept.pending import PendingSkillWrite
from skillguard.review.store import ReviewStore


def pending(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "id": "abcdef12",
                "subsystem": "skills",
                "action": "create",
                "payload": {"action": "create", "name": "receipts", "content": "# Receipts\n"},
            }
        )
    )
    return path


def test_capture_is_persistent_idempotent_and_preserves_pending(tmp_path: Path) -> None:
    source = pending(tmp_path / "pending.json")
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(source)
    assert store.capture(source) == review_id
    reopened = ReviewStore(tmp_path / "reviews")
    assert reopened.get(review_id)["name"] == "receipts"
    assert source.exists()
    assert reopened.decide(review_id)["decision"] == "held"
    assert not (tmp_path / "skills").exists()


def test_concurrent_capture_materializes_one_snapshot(tmp_path: Path, monkeypatch) -> None:
    source = pending(tmp_path / "pending.json")
    stores = [ReviewStore(tmp_path / "reviews") for _ in range(2)]
    start = Barrier(2)
    materializations = []
    original = PendingSkillWrite.materialize_create

    def materialize(candidate, folder):
        materializations.append(candidate.sha256)
        time.sleep(0.1)
        return original(candidate, folder)

    monkeypatch.setattr(PendingSkillWrite, 'materialize_create', materialize)

    def capture(store):
        start.wait(timeout=5)
        return store.capture(source)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(capture, store) for store in stores]
        ids = [future.result(timeout=10) for future in futures]
    assert ids[0] == ids[1]
    assert materializations == [PendingSkillWrite.load(source).sha256]
    assert stores[0].get(ids[0])['candidate_sha256'] == stores[1].get(ids[1])['candidate_sha256']


def test_modified_snapshot_cannot_receive_a_decision(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    snapshot = Path(store.get(review_id)["snapshot"])
    (snapshot / "SKILL.md").write_text("changed after capture")
    with pytest.raises(ValueError, match="snapshot"):
        store.decide(review_id)


def test_static_pass_and_model_allow_cannot_approve_incomplete_replay(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    store.record_static(review_id, {"overall_status": "passed", "incomplete_scans": []})
    store.record_replay(
        review_id,
        BehavioralEnvelope(),
        BehavioralEnvelope(),
        artifacts={"trace.json": b"{}"},
        functional_passed=True,
        executed_candidate_sha256=store.get(review_id)["candidate_sha256"],
    )
    response = json.loads(Path("tests/fixtures/nemotron_receipt_response.json").read_text())
    advice = json.loads(response["choices"][0]["message"]["content"])
    advice["recommendation"] = "allow"
    store.record_advice(review_id, json.dumps(advice), source="recorded")
    decision = store.decide(review_id)
    assert decision["decision"] == "held"
    assert "independent" in " ".join(decision["reasons"])


def test_unauthorized_observed_behavior_blocks_against_operator_contract(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    expected = BehavioralEnvelope(files_read=["/tmp/receipt"], files_written=["/tmp/output"])
    observed = BehavioralEnvelope(
        files_read=["/tmp/receipt", "/tmp/fake-private"],
        files_written=["/tmp/output"],
        network_hosts=["127.0.0.1:8765"],
    )
    store.record_static(review_id, {"overall_status": "passed", "incomplete_scans": []})
    store.record_contract(review_id, expected)
    store.record_replay(
        review_id,
        expected,
        observed,
        artifacts={"trace.json": b"{}"},
        functional_passed=True,
        executed_candidate_sha256=store.get(review_id)["candidate_sha256"],
    )
    decision = store.decide(review_id)
    assert decision["decision"] == "blocked"
    assert decision["unauthorized"]["files_read"] == ["/tmp/fake-private"]
    assert decision["unauthorized"]["network_hosts"] == ["127.0.0.1:8765"]


@pytest.mark.parametrize("status", ["failed", "incomplete", None])
def test_nonpassing_static_scan_never_permits_activation(tmp_path: Path, status: str) -> None:
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    store.record_static(review_id, {"overall_status": status, "incomplete_scans": []})
    assert store.decide(review_id)["decision"] in {"held", "blocked"}


def test_incomplete_summary_does_not_hide_a_failed_validator(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    store.record_static(
        review_id,
        {
            "overall_status": "incomplete",
            "incomplete_scans": ["skillspector"],
            "results": [{"validator": "Schema", "status": "failed"}],
        },
    )
    decision = store.decide(review_id)
    assert decision["decision"] == "blocked"
    assert decision["failed_static_checks"] == ["Schema"]
    assert not decision["activation_permitted"]


def test_evidence_tampering_prevents_decision(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    event = store.record_static(review_id, {"overall_status": "passed", "incomplete_scans": []})
    Path(event["artifact"]).write_text('{"overall_status":"passed","altered":true}')
    with pytest.raises(ValueError, match="artifact"):
        store.decide(review_id)


def test_replay_of_a_different_candidate_is_rejected(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    with pytest.raises(ValueError, match="executed candidate"):
        store.record_replay(
            review_id,
            BehavioralEnvelope(),
            BehavioralEnvelope(),
            artifacts={"trace.json": b"{}"},
            functional_passed=True,
            executed_candidate_sha256="wrong-snapshot",
        )


def test_changed_contract_invalidates_prior_model_advice(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    response = json.loads(Path("tests/fixtures/nemotron_receipt_response.json").read_text())
    store.record_advice(review_id, response["choices"][0]["message"]["content"], source="recorded")
    store.record_contract(review_id, BehavioralEnvelope(files_read=["/tmp/receipt"]))
    assert "older evidence" in " ".join(store.decide(review_id)["reasons"])


def test_policy_is_bound_to_operator_contract_and_remains_unapplied(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending(tmp_path / "pending.json"))
    with pytest.raises(ValueError, match="contract"):
        store.record_policy_draft(review_id, runtime_read_only=["/usr"])
    store.record_contract(review_id, BehavioralEnvelope(files_read=["/tmp/receipt"]))
    draft = store.record_policy_draft(review_id, runtime_read_only=["/usr"])
    assert draft["data"]["candidate_sha256"] == store.get(review_id)["candidate_sha256"]
    assert draft["data"]["applied"] is False
