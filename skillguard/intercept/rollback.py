"""Prepare a rollback through Hermes' pending-write gate, without activating it."""

from __future__ import annotations

import json
from pathlib import Path

from skillguard.intercept.pending import PendingSkillWrite
from skillguard.intercept.reconstruct import checked_mutation
from skillguard.review.snapshot import snapshot_digest
from skillguard.review.store import ReviewStore


def rollback_operations(name: str, current: Path, target: Path) -> list[dict]:
    snapshot_digest(current)
    snapshot_digest(target)
    current_files = {
        p.relative_to(current).as_posix(): p.read_bytes() for p in current.rglob("*") if p.is_file()
    }
    target_files = {
        p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }
    ops = []
    for path, raw in sorted(target_files.items()):
        if raw == current_files.get(path):
            continue
        content = raw.decode("utf-8")  # Binary rollback is deliberately unsupported.
        if path == "SKILL.md":
            ops.append({"action": "patch", "name": name, "content": content})
        else:
            ops.append(
                {"action": "write_file", "name": name, "file_path": path, "file_content": content}
            )
    for path in sorted(current_files.keys() - target_files.keys()):
        ops.append({"action": "remove_file", "name": name, "file_path": path})
    if not ops:
        raise ValueError("installed skill already matches rollback target")
    raw = json.dumps(
        {
            "id": "00000000",
            "subsystem": "skills",
            "action": "batch",
            "payload": {"action": "batch", "operations": ops},
        }
    ).encode()
    candidate = PendingSkillWrite("00000000", name, "batch", None, raw)
    checked_mutation(candidate)
    return ops


def stage_rollback(
    store: ReviewStore, review_id: str, *, hermes_home: Path, expected_active_sha256: str
) -> dict:
    from hermes_constants import get_hermes_home
    from tools.skill_manager_tool import _find_skill, skill_manage
    from tools.write_approval import write_approval_enabled

    if get_hermes_home().resolve() != hermes_home.resolve():
        raise ValueError("Hermes profile does not match rollback target")
    if not write_approval_enabled("skills"):
        raise ValueError("Hermes write approval must be enabled")
    review = store.get(review_id)
    base = review["latest"].get("baseline")
    if not base:
        raise ValueError("review has no archived installed version")
    installed = _find_skill(review["name"])
    if not installed or not installed["path"].resolve().is_relative_to(hermes_home.resolve()):
        raise ValueError("rollback requires a skill in the selected Hermes profile")
    current = installed["path"]
    if snapshot_digest(current) != expected_active_sha256:
        raise ValueError("installed version changed; re-review before rollback")
    ops = rollback_operations(review["name"], current, Path(base["snapshot"]))
    result = json.loads(skill_manage(action="", name="", operations=ops))
    if result.get("staged") is not True:
        raise RuntimeError("Hermes did not stage the rollback")
    if snapshot_digest(current) != expected_active_sha256:
        raise RuntimeError("installed skill changed while staging rollback")
    pending = hermes_home / "pending/skills" / f"{result['pending_id']}.json"
    captured = PendingSkillWrite.load(pending)
    return store.record_rollback_staged(
        review_id,
        {
            "pending_id": captured.pending_id,
            "pending_sha256": captured.sha256,
            "active_sha256": expected_active_sha256,
            "target_sha256": base["sha256"],
            "activation_permitted": False,
            "status": "staged for a new review",
        },
    )
