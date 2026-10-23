import json
from pathlib import Path

import pytest

from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.intercept.reconstruct import checked_mutation
from skillguard.review.snapshot import snapshot_digest
from skillguard.review.store import ReviewStore


def mutation(tmp_path, *, action="patch", **fields):
    path = tmp_path / "pending.json"
    path.write_text(
        json.dumps(
            {
                "id": "abcdef12",
                "subsystem": "skills",
                "action": action,
                "payload": {"action": action, "name": "receipts", **fields},
            }
        )
    )
    return path


def baseline(tmp_path):
    path = tmp_path / "active" / "receipts"
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("original")
    (path / "scripts").mkdir()
    (path / "scripts/run.py").write_text("print('original')")
    return path


def apply_copy(profile, payload):
    assert (profile / "config.yaml").read_text().endswith("true\n")
    (profile / "skills/receipts/SKILL.md").write_text(payload["new_string"])
    return {"success": True}


def test_mutation_archives_both_versions_without_touching_active(tmp_path):
    active = baseline(tmp_path)
    original = snapshot_digest(active)
    pending = mutation(tmp_path, old_string="original", new_string="proposed")
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(pending, baseline=active, native_apply=apply_copy)
    review = store.get(review_id)
    assert (Path(review["snapshot"]) / "SKILL.md").read_text() == "proposed"
    base = Path(review["latest"]["baseline"]["snapshot"])
    assert (base / "SKILL.md").read_text() == "original"
    assert snapshot_digest(active) == original
    assert pending.is_file()
    assert store.capture(pending, baseline=active, native_apply=apply_copy) == review_id
    assert store.decide(review_id)["activation_permitted"] is False
    # Same pending mutation applied to a different baseline must be a new review.
    (active / "scripts/run.py").write_text("print('new baseline')")
    assert store.capture(pending, baseline=active, native_apply=apply_copy) != review_id


def test_baseline_archive_tampering_blocks_review(tmp_path):
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(
        mutation(tmp_path, new_string="proposed"),
        baseline=baseline(tmp_path),
        native_apply=apply_copy,
    )
    archived = Path(store.get(review_id)["latest"]["baseline"]["snapshot"])
    (archived / "SKILL.md").write_text("changed")
    with pytest.raises(ValueError, match="baseline snapshot changed"):
        store.decide(review_id)


def test_mutation_replay_must_identify_its_original_installed_version(tmp_path):
    store = ReviewStore(tmp_path / "reviews")
    review_id = store.capture(
        mutation(tmp_path, new_string="proposed"),
        baseline=baseline(tmp_path),
        native_apply=apply_copy,
    )
    review = store.get(review_id)
    args = dict(
        artifacts={"trace": b"{}"},
        functional_passed=True,
        executed_candidate_sha256=review["candidate_sha256"],
    )
    with pytest.raises(ValueError, match="executed baseline"):
        store.record_replay(review_id, BehavioralEnvelope(), BehavioralEnvelope(), **args)
    with pytest.raises(ValueError, match="executed baseline"):
        store.record_replay(
            review_id,
            BehavioralEnvelope(),
            BehavioralEnvelope(),
            executed_baseline_sha256="other-version",
            **args,
        )
    event = store.record_replay(
        review_id,
        BehavioralEnvelope(),
        BehavioralEnvelope(),
        executed_baseline_sha256=review["latest"]["baseline"]["sha256"],
        **args,
    )
    assert event["data"]["baseline_sha256"] == review["latest"]["baseline"]["sha256"]


def test_native_rejection_does_not_register_candidate_or_modify_active(tmp_path):
    store = ReviewStore(tmp_path / "reviews")
    active = baseline(tmp_path)
    original = snapshot_digest(active)
    with pytest.raises(ValueError, match="native Hermes rejected"):
        store.capture(
            mutation(tmp_path), baseline=active, native_apply=lambda *_: {"success": False}
        )
    assert snapshot_digest(active) == original
    assert not list((store.root / "snapshots").glob("*/candidate"))


@pytest.mark.parametrize("path", ["../escape", "scripts/../SKILL.md", "/tmp/a", "SKILL.md/a"])
def test_unsafe_mutation_is_rejected_before_native_call(tmp_path, path):
    store = ReviewStore(tmp_path / "reviews")
    with pytest.raises(ValueError, match="unsafe"):
        store.capture(
            mutation(tmp_path, file_path=path),
            baseline=baseline(tmp_path),
            native_apply=lambda *_: pytest.fail("must not call native Hermes"),
        )


def test_symlink_baseline_is_rejected(tmp_path):
    active = baseline(tmp_path)
    (active / "scripts/secret-link").symlink_to(tmp_path / "private-file")
    with pytest.raises(ValueError, match="symlink"):
        snapshot_digest(active)


def test_delete_remains_unsupported(tmp_path):
    from skillguard.intercept.pending import PendingSkillWrite

    with pytest.raises(ValueError, match="deletion"):
        checked_mutation(PendingSkillWrite.load(mutation(tmp_path, action="delete")))
