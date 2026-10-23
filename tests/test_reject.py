import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from skillguard.intercept.reject import reject_pending
from skillguard.review.store import ReviewStore


@pytest.fixture
def native(tmp_path: Path, monkeypatch):
    home = tmp_path / "hermes"
    queue = home / "pending/skills"
    queue.mkdir(parents=True)
    pending = queue / "abcdef12.json"
    pending.write_text(
        json.dumps(
            {
                "id": "abcdef12",
                "subsystem": "skills",
                "action": "create",
                "payload": {"action": "create", "name": "receipts", "content": "# Receipts"},
            }
        )
    )
    constants = ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: home
    wa = ModuleType("tools.write_approval")
    wa.write_approval_enabled = lambda subsystem: True
    calls = []

    def discard(subsystem, pending_id):
        calls.append(pending_id)
        pending.unlink()
        return True

    wa.discard_pending = discard
    wa.get_pending = lambda subsystem, pid: (
        json.loads(pending.read_text()) if pending.exists() else None
    )
    monkeypatch.setitem(sys.modules, "hermes_constants", constants)
    monkeypatch.setitem(sys.modules, "tools", ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.write_approval", wa)
    store = ReviewStore(tmp_path / "reviews")
    rid = store.capture(pending)
    return home, pending, store, rid, calls, wa


def test_blocked_pending_is_removed_but_snapshot_is_preserved(native) -> None:
    home, pending, store, rid, calls, _ = native
    store.record_static(rid, {"overall_status": "failed"})
    result = reject_pending(store, rid, hermes_home=home)
    assert result["data"]["pending_removed"]
    assert calls == ["abcdef12"]
    assert not pending.exists()
    assert (Path(store.get(rid)["snapshot"]).parent / "pending.json").exists()


def test_held_candidate_cannot_be_discarded(native) -> None:
    home, pending, store, rid, calls, _ = native
    with pytest.raises(ValueError, match="blocked"):
        reject_pending(store, rid, hermes_home=home)
    assert pending.exists() and not calls


def test_changed_pending_cannot_be_rejected_using_an_old_review(native) -> None:
    home, pending, store, rid, calls, _ = native
    value = json.loads(pending.read_text())
    value["payload"]["content"] = "newer candidate"
    pending.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="changed"):
        reject_pending(store, rid, hermes_home=home)
    assert pending.exists() and not calls


def test_wrong_profile_cannot_be_modified(native, tmp_path: Path) -> None:
    _, pending, store, rid, calls, _ = native
    with pytest.raises(ValueError, match="profile"):
        reject_pending(store, rid, hermes_home=tmp_path / "unrelated")
    assert pending.exists() and not calls


def test_disabled_native_gate_prevents_rejection_workflow(native) -> None:
    home, pending, store, rid, calls, wa = native
    wa.write_approval_enabled = lambda subsystem: False
    with pytest.raises(ValueError, match="enabled"):
        reject_pending(store, rid, hermes_home=home)
    assert pending.exists() and not calls
