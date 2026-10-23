"""Verify native existing-skill reconstruction and staged rollback, without inference."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from skillguard.intercept.reconstruct import HermesReconstructor
from skillguard.intercept.rollback import stage_rollback
from skillguard.review.snapshot import snapshot_digest
from skillguard.review.store import ReviewStore


def main() -> None:
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.skill_manager_tool import skill_manage
    from tools.write_approval import get_pending, write_approval_enabled

    root = Path(__file__).resolve().parents[1]
    run_id = uuid.uuid4().hex[:12]
    run = root / "results/integration" / f"mutation-{run_id}"
    profile = run / "hermes-profile"
    active = profile / "skills/invoice-organizer"
    shutil.copytree(root / "skills/benign/invoice-organizer", active)
    (active / "references").mkdir()
    (active / "references/obsolete.txt").write_text("old receipt instructions\n")
    (profile / "config.yaml").write_text("skills:\n  write_approval: true\n")
    original_sha = snapshot_digest(active)
    native_apply = HermesReconstructor(root.parent / "work/hermes-agent")
    store = ReviewStore(run / "reviews")
    token = set_hermes_home_override(profile)
    try:
        assert write_approval_enabled("skills")
        operations = [
            {
                "action": "patch",
                "name": "invoice-organizer",
                "old_string": "# Invoice Organizer",
                "new_string": "# Receipt Organizer",
            },
            {
                "action": "write_file",
                "name": "invoice-organizer",
                "file_path": "scripts/run.py",
                "file_content": "print('local receipt summary')\n",
            },
            {
                "action": "write_file",
                "name": "invoice-organizer",
                "file_path": "references/receipt.txt",
                "file_content": "local-only receipt guide\n",
            },
            {
                "action": "remove_file",
                "name": "invoice-organizer",
                "file_path": "references/obsolete.txt",
            },
        ]
        staged = json.loads(skill_manage(action="", name="", operations=operations))
        assert staged.get("staged") is True, staged
        pending = profile / "pending/skills" / f"{staged['pending_id']}.json"
        review_id = store.capture(pending, baseline=active, native_apply=native_apply)
        review = store.get(review_id)
        candidate = Path(review["snapshot"])
        assert "# Receipt Organizer" in (candidate / "SKILL.md").read_text()
        assert (candidate / "scripts/run.py").read_text() == "print('local receipt summary')\n"
        assert (candidate / "references/receipt.txt").is_file()
        assert not (candidate / "references/obsolete.txt").exists()
        assert snapshot_digest(active) == original_sha
        assert get_pending("skills", staged["pending_id"]) is not None

        # Full rewrite uses native legacy edit, also only in the disposable copy.
        edit = json.loads(
            skill_manage(
                action="edit",
                name="invoice-organizer",
                content=(active / "SKILL.md").read_text() + "\nLocal edit.\n",
            )
        )
        assert edit.get("staged") is True
        edit_id = store.capture(
            profile / "pending/skills" / f"{edit['pending_id']}.json",
            baseline=active,
            native_apply=native_apply,
        )
        assert (
            (Path(store.get(edit_id)["snapshot"]) / "SKILL.md")
            .read_text()
            .endswith("Local edit.\n")
        )
        assert snapshot_digest(active) == original_sha

        # Operator-controlled test setup: simulate an installed changed version.
        # This is not SkillGuard approval or a production activation operation.
        shutil.rmtree(active)
        shutil.copytree(candidate, active)
        changed_sha = snapshot_digest(active)
        rollback = stage_rollback(
            store, review_id, hermes_home=profile, expected_active_sha256=changed_sha
        )["data"]
        rollback_path = profile / "pending/skills" / f"{rollback['pending_id']}.json"
        rollback_review_id = store.capture(
            rollback_path, baseline=active, native_apply=native_apply
        )
        restored = store.get(rollback_review_id)
        assert restored["candidate_sha256"] == original_sha
        assert snapshot_digest(active) == changed_sha
        assert get_pending("skills", rollback["pending_id"]) is not None
        assert store.decide(rollback_review_id)["activation_permitted"] is False
        report = {
            "run_id": run_id,
            "mutation_review": review_id,
            "edit_review": edit_id,
            "rollback_review": rollback_review_id,
            "original_sha256": original_sha,
            "candidate_sha256": changed_sha,
            "rollback_candidate_sha256": original_sha,
            "patch_write_remove_reconstructed": True,
            "full_edit_reconstructed": True,
            "initial_installed_version_unchanged": True,
            "rollback_staged_not_activated": True,
            "rollback_exact_content_match": True,
            "native_write_gate_enabled": True,
            "scope": "Real Hermes native text mutations in disposable profiles; "
            "operator simulates installed update for rollback test. "
            "No model, script execution, production approval, or full agent session.",
        }
        (run / "mutation.json").write_text(json.dumps(report, indent=2) + "\n")
        (root / "results/mutation-latest.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        reset_hermes_home_override(token)


if __name__ == "__main__":
    main()
