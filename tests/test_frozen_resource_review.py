import json
from pathlib import Path

import pytest

from skillguard.evaluation.receipt_grader import grade_payloads
from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore
from tests.test_candidate_execution_review import fixture


def native_fixture(tmp_path, *, passed=False):
    store, rid, _, _ = fixture(tmp_path)
    expected = {"clear": {"total": 24.73}}
    outputs = {"clear": json.dumps({"total": 24.73 if passed else 21.50})}
    reward = grade_payloads(outputs, expected)
    trial = {"agent_info": {"name": "oracle", "model_info": None},
             "exception_info": None, "finished_at": "2026-10-02T18:45:54Z",
             "verifier_result": {"rewards": {"overall": reward["overall"],
                                             **reward["custom_metrics"]}}}
    review = store.get(rid)
    artifacts = {
        "trial.json": json.dumps(trial).encode(), "reward.json": json.dumps(reward).encode(),
        "parser.py": (Path(review["snapshot"]) / "scripts/parse_receipt.py").read_bytes(),
        "expectations.json": json.dumps(expected).encode(),
        "outputs.json": json.dumps(outputs).encode(),
    }
    report = {"scope": "bounded_native_harbor_oracle", "complete": False,
              "activation_eligible": False, "candidate_sha256": review["candidate_sha256"],
              "skill_lift": None, "artifacts": {k: digest(v) for k, v in artifacts.items()}}
    return store, rid, report, artifacts


@pytest.mark.parametrize("passed", [True, False])
def test_native_checks_persist_without_approval_or_raw_model_inputs(tmp_path, passed):
    store, rid, report, artifacts = native_fixture(tmp_path, passed=passed)
    store.record_frozen_resource_evaluation(rid, report=json.dumps(report).encode(),
                                            artifacts=artifacts)
    reopened = ReviewStore(store.root)
    evidence = reopened.evidence(rid)["E10"]["value"]
    assert evidence["functional_passed"] is passed
    assert evidence["complete"] is False
    assert "24.73" not in json.dumps(evidence)
    assert reopened.decide(rid)["activation_permitted"] is False
    if not passed:
        assert "Native frozen-resource domain checks failed" in reopened.decide(rid)["reasons"]


@pytest.mark.parametrize("change", ["candidate", "source", "reward", "output", "error", "model"])
def test_cannot_relabel_or_forge_frozen_native_evidence(tmp_path, change):
    store, rid, report, artifacts = native_fixture(tmp_path)
    if change == "candidate":
        report["candidate_sha256"] = "b" * 64
    elif change == "source":
        artifacts["parser.py"] = b"changed source"
    elif change == "reward":
        artifacts["reward.json"] = b'{"overall":1}'
    elif change == "output":
        artifacts["outputs.json"] = b'{"clear":"{\\"total\\":24.73}"}'
    else:
        trial = json.loads(artifacts["trial.json"])
        if change == "error":
            trial["exception_info"] = {"error": "verifier failed"}
        else:
            trial["agent_info"]["model_info"] = {"name": "live model"}
        artifacts["trial.json"] = json.dumps(trial).encode()
    report["artifacts"] = {k: digest(v) for k, v in artifacts.items()}
    with pytest.raises(ValueError):
        store.record_frozen_resource_evaluation(rid, report=json.dumps(report).encode(),
                                                artifacts=artifacts)


def test_archived_native_attachment_tampering_fails_after_reopen(tmp_path):
    store, rid, report, artifacts = native_fixture(tmp_path)
    event = store.record_frozen_resource_evaluation(rid, report=json.dumps(report).encode(),
                                                   artifacts=artifacts)
    Path(event["data"]["attachments"][0]["artifact"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifact changed"):
        ReviewStore(store.root).decide(rid)


def frozen_fixture(tmp_path, split, *, passed=True):
    store, rid, report, artifacts = native_fixture(tmp_path, passed=passed)
    from tests.test_receipt_repair_contract import fixture as freeze_fixture

    manifest = freeze_fixture(tmp_path / "contract")
    suite = json.loads((manifest.parent / f"{split}.json").read_text())
    cases = suite["cases"]
    expected = {k: v["expected"] for k, v in cases.items()}
    outputs = {k: json.dumps(v if passed else {**v, "total": -1}) for k, v in expected.items()}
    reward = grade_payloads(outputs, expected)
    trial = json.loads(artifacts["trial.json"])
    trial["verifier_result"]["rewards"] = {"overall": reward["overall"], **reward["custom_metrics"]}
    artifacts.update({"trial.json": json.dumps(trial).encode(),
        "reward.json": json.dumps(reward).encode(),
        "expectations.json": json.dumps(expected).encode(),
        "outputs.json": json.dumps(outputs).encode(), "contract.json": manifest.read_bytes(),
        "suite.json": (manifest.parent / f"{split}.json").read_bytes(),
        "inputs.json": json.dumps({k: v["input"] for k, v in cases.items()}).encode()})
    report.update({"contract_split": split,
                   "contract_manifest_sha256": digest(manifest.read_bytes()),
                   "artifacts": {k: digest(v) for k, v in artifacts.items()}})
    return store, rid, report, artifacts, manifest


def test_passing_one_split_cannot_claim_all_frozen_checks_passed(tmp_path):
    store, rid, report, artifacts, _ = frozen_fixture(tmp_path, "heldout")
    store.record_frozen_resource_evaluation(rid, report=json.dumps(report).encode(),
                                            artifacts=artifacts)
    evidence = store.evidence(rid)["E10"]["value"]
    assert evidence["functional_passed"] is False
    assert evidence["frozen_splits"]["heldout"]["passed"] is True
    assert "Frozen development or unseen checks missing" in store.decide(rid)["reasons"]
    assert store.decide(rid)["activation_permitted"] is False


@pytest.mark.parametrize("change", ["input", "expectation", "suite"])
def test_frozen_checks_cannot_be_changed_even_with_new_artifact_hashes(tmp_path, change):
    store, rid, report, artifacts, _ = frozen_fixture(tmp_path, "development")
    if change == "input":
        artifacts["inputs.json"] = b'{}'
    elif change == "expectation":
        artifacts["expectations.json"] = b'{}'
    else:
        artifacts["suite.json"] += b' '
    report["artifacts"] = {k: digest(v) for k, v in artifacts.items()}
    with pytest.raises(ValueError, match="frozen"):
        store.record_frozen_resource_evaluation(rid, report=json.dumps(report).encode(),
                                                artifacts=artifacts)


def replace_split(report, artifacts, manifest, split, *, passed):
    suite = (manifest.parent / f"{split}.json").read_bytes()
    cases = json.loads(suite)["cases"]
    expected = {name: case["expected"] for name, case in cases.items()}
    outputs = {k: json.dumps(v if passed else v | {"total": -1}) for k, v in expected.items()}
    reward = grade_payloads(outputs, expected)
    trial = json.loads(artifacts["trial.json"])
    trial["verifier_result"]["rewards"] = {"overall": reward["overall"], **reward["custom_metrics"]}
    updated = artifacts | {"suite.json": suite, "expectations.json": json.dumps(expected).encode(),
        "inputs.json": json.dumps({k: v["input"] for k, v in cases.items()}).encode(),
        "outputs.json": json.dumps(outputs).encode(), "reward.json": json.dumps(reward).encode(),
        "trial.json": json.dumps(trial).encode()}
    return report | {"contract_split": split,
        "artifacts": {k: digest(v) for k, v in updated.items()}}, updated


@pytest.mark.parametrize("development_passed", [True, False])
def test_unseen_success_does_not_hide_development_failure(tmp_path, development_passed):
    store, rid, report, artifacts, manifest = frozen_fixture(
        tmp_path, "development", passed=development_passed)
    store.record_frozen_resource_evaluation(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    report, artifacts = replace_split(report, artifacts, manifest, "heldout", passed=True)
    store.record_frozen_resource_evaluation(rid, report=json.dumps(report).encode(),
                                           artifacts=artifacts)
    value = ReviewStore(store.root).evidence(rid)["E10"]["value"]
    assert value["functional_passed"] is development_passed
    assert set(value["frozen_splits"]) == {"development", "heldout"}
    assert "24.73" not in json.dumps(value)
    assert store.decide(rid)["activation_permitted"] is False
    if not development_passed:
        report, artifacts = replace_split(report, artifacts, manifest, "development", passed=True)
        store.record_frozen_resource_evaluation(rid, report=json.dumps(report).encode(),
                                               artifacts=artifacts)
        assert store.evidence(rid)["E10"]["value"]["functional_passed"] is False
