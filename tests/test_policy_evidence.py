import json

import pytest

from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.review.store import ReviewStore


def review(tmp_path):
    path = tmp_path / "pending.json"
    path.write_text(
        json.dumps(
            {
                "id": "abcdef12",
                "subsystem": "skills",
                "action": "create",
                "payload": {"action": "create", "name": "receipts", "content": "# Receipts"},
            }
        )
    )
    store = ReviewStore(tmp_path / "reviews")
    rid = store.capture(path)
    store.record_contract(
        rid,
        BehavioralEnvelope(files_read=["/sandbox/receipt.txt"], files_written=["/sandbox/out.txt"]),
    )
    policy = store.record_policy_draft(rid, runtime_read_only=["/usr"])["data"]["policy"]
    base = {"uid": 1000, "private_mode": "0o644", "receipt_read": True, "output_written": True}
    inputs = {
        "executed_candidate_sha256": store.get(rid)["candidate_sha256"],
        "rootfs_sha256": "a" * 64,
        "native_policy": json.dumps({"policy": policy}).encode(),
        "permissive_result": json.dumps(base | {"private_read": True}).encode(),
        "restricted_result": json.dumps(
            base | {"private_read": False, "private_errno": 13}
        ).encode(),
    }
    return store, rid, inputs


def test_file_probe_binds_native_policy_and_candidate_but_does_not_approve(tmp_path):
    store, rid, inputs = review(tmp_path)
    event = store.record_file_enforcement(rid, **inputs)
    assert event["data"]["status"] == "file_canary_verified"
    assert len(event["data"]["attachments"]) == 3
    assert store.decide(rid)["activation_permitted"] is False
    assert "E5" in store.evidence(rid)


@pytest.mark.parametrize("mismatch", ["candidate", "policy", "functional", "denial", "contract"])
def test_wrong_or_stale_enforcement_evidence_is_rejected(tmp_path, mismatch):
    store, rid, inputs = review(tmp_path)
    if mismatch == "candidate":
        inputs["executed_candidate_sha256"] = "other"
    elif mismatch == "policy":
        inputs["native_policy"] = b'{"policy":{"version":1}}'
    elif mismatch in {"functional", "denial"}:
        restricted = json.loads(inputs["restricted_result"])
        restricted["receipt_read" if mismatch == "functional" else "private_read"] = (
            mismatch == "denial"
        )
        inputs["restricted_result"] = json.dumps(restricted).encode()
    else:
        store.record_contract(rid, BehavioralEnvelope(files_read=["/different/file"]))
    with pytest.raises(ValueError):
        store.record_file_enforcement(rid, **inputs)
    assert "file_enforcement" not in store.get(rid)["latest"]


def test_changed_policy_invalidates_an_earlier_file_probe(tmp_path):
    store, rid, inputs = review(tmp_path)
    store.record_file_enforcement(rid, **inputs)
    store.record_policy_draft(rid, runtime_read_only=["/usr", "/etc"])
    assert "Policy enforcement missing or refers to an older policy" in store.decide(rid)["reasons"]


@pytest.mark.parametrize("uid", [None, 0, True, "1000"])
def test_file_probe_requires_an_explicit_nonroot_execution_identity(tmp_path, uid):
    store, rid, inputs = review(tmp_path)
    for key in ("permissive_result", "restricted_result"):
        result = json.loads(inputs[key])
        result["uid"] = uid
        inputs[key] = json.dumps(result).encode()
    with pytest.raises(ValueError, match="controlled private-read denial"):
        store.record_file_enforcement(rid, **inputs)
