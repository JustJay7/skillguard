from __future__ import annotations

from pathlib import Path

from skillguard.intercept.pending import PendingSkillWrite
from skillguard.review.store import ReviewStore


def reject_pending(store: ReviewStore, review_id: str, *, hermes_home: Path) -> dict:
    """Reject a reviewed candidate through Hermes, preserving its archived snapshot.

    The caller must select the intended Hermes profile before invoking this method.
    This controls the supported pending-write route, not arbitrary terminal writes
    or direct native approval calls by an operator.
    """
    from hermes_constants import get_hermes_home
    from tools.write_approval import discard_pending, get_pending, write_approval_enabled

    if get_hermes_home().resolve() != hermes_home.resolve():
        raise ValueError("Hermes profile does not match rejection target")
    if not write_approval_enabled("skills"):
        raise ValueError("Hermes write approval must be enabled")
    review = store.get(review_id)
    archived = PendingSkillWrite.load(Path(review["snapshot"]).parent / "pending.json")
    path = hermes_home / "pending/skills" / f"{archived.pending_id}.json"
    current = PendingSkillWrite.load(path)
    if current.sha256 != review["pending_sha256"]:
        raise ValueError("pending write changed since review capture")
    decision = store.decide(review_id)
    if decision["decision"] != "blocked":
        raise ValueError("only a blocked review can be rejected")
    if not discard_pending("skills", current.pending_id):
        raise RuntimeError("Hermes did not discard the blocked pending candidate")
    if get_pending("skills", current.pending_id) is not None:
        raise RuntimeError("blocked candidate remains in Hermes approval queue")
    return store.record_rejection(
        review_id,
        {
            "pending_id": current.pending_id,
            "profile": str(hermes_home.resolve()),
            "pending_removed": True,
            "archive_preserved": True,
        },
    )
