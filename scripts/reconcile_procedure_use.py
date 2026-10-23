"""Recheck saved native conversations and reject a blocked disposable candidate.

No model requests. Earlier reports and ordered review history remain intact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.hermes_procedure_use_probe import EXPECTED, LEARNED_SHA
from skillguard.evaluation.procedure_use import check_procedure_use
from skillguard.intercept.reconstruct import HermesReconstructor
from skillguard.review.store import ReviewStore


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    if not run.is_relative_to(root / "results/integration"):
        parser.error("recorded run must be inside the integration results directory")
    original_report = json.loads((run / "procedure-use.json").read_text())
    rid = original_report["review_id"]
    store = ReviewStore(run / "reviews")
    review = store.get(rid)
    if review["candidate_sha256"] != LEARNED_SHA:
        raise RuntimeError("this probe targets only the inspected learned receipt guide")
    skill_text = (Path(review["snapshot"]) / "SKILL.md").read_text()
    raw_artifacts = {
        item["label"]: Path(item["artifact"]).read_bytes()
        for item in review["latest"]["procedure_use"]["attachments"]
    }
    cases = {}
    for label, raw in raw_artifacts.items():
        if label.endswith("_conversation.json"):
            name = label.removesuffix("_conversation.json")
            cases[name] = check_procedure_use(
                json.loads(raw), skill_text=skill_text, expected=EXPECTED
            )
    if "rejection" not in review["latest"]:
        store.record_procedure_use(
            rid, executed_candidate_sha256=LEARNED_SHA,
            cases=cases, artifacts=raw_artifacts,
        )
    decision = store.decide(rid)
    rejection = review["latest"].get("rejection")
    profile = root / "results/integration/learning-3436408c069e/hermes-profile"
    if decision["decision"] == "blocked" and rejection is None:
        source = root.parent / "work/hermes-agent"
        HermesReconstructor(source)
        sys.path.insert(0, str(source))
        from hermes_constants import reset_hermes_home_override, set_hermes_home_override

        from skillguard.intercept.reject import reject_pending

        token = set_hermes_home_override(profile)
        try:
            rejection = reject_pending(store, rid, hermes_home=profile)["data"]
        finally:
            reset_hermes_home_override(token)
    # Continue the actual learning review's history as well as the replay copy.
    learning_store = ReviewStore(profile.parent / "reviews")
    learning_review = learning_store.get(rid)
    if learning_review["candidate_sha256"] != LEARNED_SHA:
        raise RuntimeError("original learning review does not match replay candidate")
    if "rejection" not in learning_review["latest"]:
        learning_store.record_procedure_use(
            rid, executed_candidate_sha256=LEARNED_SHA,
            cases=cases, artifacts=raw_artifacts,
        )
        if rejection:
            if (profile / "pending/skills/20d4acf4.json").exists():
                raise RuntimeError("native rejection state changed")
            learning_store.record_rejection(rid, rejection | {
                "source": "Verified native rejection in archived procedure-use review",
            })
    report = {
        "recorded_run": str(run), "review_id": rid,
        "source_report_preserved": True, "recomputed_cases": cases,
        "unsafe_tool_requests": store.get(rid)["latest"]["procedure_use"]["unsafe_tool_requests"],
        "decision": decision, "rejection": rejection,
        "original_pending_present": (profile / "pending/skills/20d4acf4.json").exists(),
        "original_active_skill_absent": not (
            profile / "skills/receipt-organizer/SKILL.md"
        ).exists(),
        "learning_review_store": str(learning_store.root),
        "learning_decision": learning_store.decide(rid),
        "model_calls": 0,
    }
    raw_report = json.dumps(report, indent=2) + "\n"
    (run / "reconciliation.json").write_text(raw_report)
    (root / "results/procedure-reconciliation-latest.json").write_text(raw_report)
    print(raw_report)


if __name__ == "__main__":
    main()
