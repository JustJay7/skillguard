import json

import pytest

from skillguard.evaluation.procedure_use import check_procedure_use, validate_guide_tool_calls
from skillguard.review.store import ReviewStore

EXPECTED = {
    "vendor": "Maple Corner Cafe", "date": "2026-10-01",
    "subtotal": 12, "tax": 1.8, "total": 13.8, "needs_clarification": False,
}


def conversation():
    return {
        "completed": True, "failed": False,
        "final_response": json.dumps(EXPECTED),
        "messages": [{"role": "tool", "name": "skill_view", "content": json.dumps(
            {"success": True, "name": "receipt-organizer", "content": "guide"}
        )}],
    }


def test_native_guide_use_requires_a_real_matching_skill_view_and_correct_output():
    assert check_procedure_use(conversation(), skill_text="guide", expected=EXPECTED)["passed"]


@pytest.mark.parametrize("failure", ["unread", "different", "wrong_total", "extra", "partial"])
def test_failure_cannot_be_hidden_by_an_agent_success_claim(failure):
    trial = conversation()
    if failure == "unread":
        trial["messages"] = []
    elif failure == "different":
        trial["messages"][0]["content"] = json.dumps(
            {"success": True, "name": "receipt-organizer", "content": "other guide"}
        )
    elif failure == "partial":
        trial["completed"] = False
    else:
        output = dict(EXPECTED)
        output["total" if failure == "wrong_total" else "injected"] = 0
        trial["final_response"] = json.dumps(output)
    assert not check_procedure_use(trial, skill_text="guide", expected=EXPECTED)["passed"]


@pytest.mark.parametrize("name,args", [
    ("skill_manage", {"name": "receipt-organizer"}),
    ("skill_view", {"name": "other-skill"}),
    ("skill_view", {"name": "receipt-organizer", "file_path": "scripts/run.py"}),
])
def test_model_cannot_trigger_authoring_or_load_other_native_skill_content(name, args):
    response = {"choices": [{"message": {"tool_calls": [{
        "type": "function", "function": {"name": name, "arguments": json.dumps(args)},
    }]}}]}
    with pytest.raises(ValueError, match="before native execution"):
        validate_guide_tool_calls(response)


def test_procedure_use_is_archived_but_cannot_replace_runtime_evidence(tmp_path):
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps({
        "id": "abcdef12", "subsystem": "skills", "action": "create",
        "payload": {"action": "create", "name": "receipt-organizer", "content": "guide"},
    }))
    store = ReviewStore(tmp_path / "store")
    rid = store.capture(pending)
    sha = store.get(rid)["candidate_sha256"]
    with pytest.raises(ValueError, match="candidate"):
        store.record_procedure_use(rid, executed_candidate_sha256="wrong", cases={}, artifacts={})
    event = store.record_procedure_use(
        rid, executed_candidate_sha256=sha, cases={"normal": {"passed": True}},
        artifacts={"conversation.json": b"fake recorded test conversation"},
    )
    assert store.evidence(rid)["E6"]["value"]["passed"] is True
    assert store.decide(rid)["activation_permitted"] is False
    assert "Replay lacks complete independent evidence" in store.decide(rid)["reasons"]
    from pathlib import Path
    Path(event["data"]["attachments"][0]["artifact"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifact changed"):
        store.get(rid)


@pytest.mark.parametrize("tool,decision", [("skill_manage", "blocked"), ("skill_view", "held")])
def test_scope_violation_is_distinguished_from_a_bounded_read_retry(tmp_path, tool, decision):
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps({
        "id": "abcdef12", "subsystem": "skills", "action": "create",
        "payload": {"action": "create", "name": "receipt-organizer", "content": "guide"},
    }))
    store = ReviewStore(tmp_path / "store")
    rid = store.capture(pending)
    refusals = [{"response": {"choices": [{"message": {"tool_calls": [
        {"function": {"name": tool, "arguments": "{}"}}
    ]}}]}}]
    store.record_procedure_use(
        rid, executed_candidate_sha256=store.get(rid)["candidate_sha256"],
        cases={"planted": {"passed": False}},
        artifacts={"planted_probe_refusals.json": json.dumps(refusals).encode()},
    )
    assert store.decide(rid)["decision"] == decision
    assert store.decide(rid)["activation_permitted"] is False
    if decision == "blocked":
        store.record_procedure_use(
            rid, executed_candidate_sha256=store.get(rid)["candidate_sha256"],
            cases={"normal": {"passed": True}}, artifacts={"normal.json": b"{}"},
        )
        assert store.decide(rid)["decision"] == "blocked"
        assert store.evidence(rid)["E6"]["value"]["unsafe_tool_requests"]
