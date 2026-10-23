"""Connect real Hermes staging to static checks, controlled VM replay and review.

This exercises real tool/storage APIs in a temporary profile. It does not claim
a model-induced skill-learning session or independent hostile-code tracing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.evaluation.skillevaluator import SkillEvaluatorRunner
from skillguard.intercept.reject import reject_pending
from skillguard.review.store import ReviewStore


def command(args: list[str], output: Path, *, timeout: int = 180) -> None:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    output.write_text(result.stdout + "\n" + result.stderr)
    if result.returncode:
        raise RuntimeError(f"Integration command failed (exit {result.returncode}); see {output}")


def main() -> None:
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    parser = argparse.ArgumentParser()
    parser.add_argument("--live-explanation", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run_id = uuid.uuid4().hex[:12]
    run = root / "results/integration" / run_id
    run.mkdir(parents=True)
    home = run / "hermes-profile"
    home.mkdir()
    (home / "config.yaml").write_text("skills:\n  write_approval: true\n")
    token = set_hermes_home_override(home)
    store = ReviewStore(root / "results/reviews")
    sandbox = f"sg-{run_id}"
    created = False
    try:
        from tools.skill_manager_tool import _find_skill, skill_manage
        from tools.write_approval import write_approval_enabled

        assert write_approval_enabled("skills"), "native write approval is disabled"
        reviews = {}
        pending_paths = {}
        for kind, fixture, name in [
            ("baseline", "skills/benign/invoice-organizer", "invoice-organizer"),
            (
                "candidate",
                "skills/planted/poisoned-invoice-organizer",
                "poisoned-invoice-organizer",
            ),
        ]:
            source = root / fixture
            result = json.loads(
                skill_manage(
                    action="",
                    name="",
                    operations=[
                        {
                            "action": "create",
                            "name": name,
                            "content": (source / "SKILL.md").read_text(),
                        },
                        {
                            "action": "write_file",
                            "name": name,
                            "file_path": "scripts/run.py",
                            "file_content": (source / "scripts/run.py").read_text(),
                        },
                    ],
                )
            )
            assert result.get("staged") is True, result
            assert _find_skill(name) is None
            pending_paths[kind] = home / "pending/skills" / f"{result['pending_id']}.json"
            reviews[kind] = store.capture(pending_paths[kind])
            store.run_static(
                reviews[kind], SkillEvaluatorRunner(binary=str(root / ".venv/bin/skillevaluator"))
            )

        bundle = root.parent / "work/integration" / run_id / "bundle"
        bundle.mkdir(parents=True)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        shutil.copytree(root / "skillguard", bundle / "skillguard", ignore=ignore)
        (bundle / "scripts").mkdir()
        shutil.copy2(root / "scripts/local_smoke.py", bundle / "scripts/local_smoke.py")
        (bundle / "results").mkdir()
        for kind, review_id in reviews.items():
            shutil.copytree(store.get(review_id)["snapshot"], bundle / kind)
        # No .env, credentials, host profile, database, or scanner runtime enters the VM.
        command(
            [
                "openshell",
                "sandbox",
                "create",
                "--name",
                sandbox,
                "--from",
                "python:3.12-slim",
                "--detach",
                "--no-auto-providers",
                "--",
                "sleep",
                "3600",
            ],
            run / "sandbox-create.txt",
        )
        created = True
        command(
            ["openshell", "sandbox", "upload", sandbox, str(bundle), "/sandbox/receipt"],
            run / "sandbox-upload.txt",
        )
        remote = "/sandbox/receipt/bundle"
        command(
            [
                "openshell",
                "sandbox",
                "exec",
                "-n",
                sandbox,
                "--workdir",
                remote,
                "--no-login-shell",
                "--",
                "python",
                "-m",
                "scripts.local_smoke",
                "--baseline",
                f"{remote}/baseline",
                "--candidate",
                f"{remote}/candidate",
                "--output",
                f"{remote}/results",
            ],
            run / "replay-console.txt",
        )
        replay = run / "replay"
        command(
            ["openshell", "sandbox", "download", sandbox, "receipt/bundle/results", str(replay)],
            run / "download.txt",
        )
        checks = json.loads((replay / "local_smoke_checks.json").read_text())
        assert checks["baseline_sha256"] == store.get(reviews["baseline"])["candidate_sha256"]
        before = BehavioralEnvelope.from_dict(
            json.loads((replay / "local_smoke_before.json").read_text())
        )
        after = BehavioralEnvelope.from_dict(
            json.loads((replay / "local_smoke_after.json").read_text())
        )
        review_id = reviews["candidate"]
        store.record_contract(review_id, BehavioralEnvelope.from_dict(checks["operator_contract"]))
        store.record_replay(
            review_id,
            before,
            after,
            artifacts={p.name: p.read_bytes() for p in replay.glob("*.json")},
            functional_passed=checks["functional_passed"],
            executed_candidate_sha256=checks["candidate_sha256"],
        )
        store.record_contract(
            reviews["baseline"], BehavioralEnvelope.from_dict(checks["operator_contract"])
        )
        store.record_replay(
            reviews["baseline"],
            before,
            before,
            artifacts={
                "baseline.json": (replay / "local_smoke_before.json").read_bytes(),
                "checks.json": (replay / "local_smoke_checks.json").read_bytes(),
            },
            functional_passed=checks["functional_passed"],
            executed_candidate_sha256=checks["baseline_sha256"],
        )
        baseline_decision = store.decide(reviews["baseline"])
        assert baseline_decision["decision"] == "held"
        command(["openshell", "sandbox", "get", sandbox, "-o", "json"], run / "runtime-policy.txt")
        runtime = json.loads((run / "runtime-policy.txt").read_text())["policy"]
        policy = store.record_policy_draft(
            review_id, runtime_read_only=runtime["filesystem_policy"]["read_only"]
        )
        if args.live_explanation:
            command(
                [
                    sys.executable,
                    "-m",
                    "scripts.explain_receipt_demo",
                    "--store",
                    str(store.root),
                    "--review",
                    review_id,
                ],
                run / "model-console.txt",
            )
        decision = store.decide(review_id)
        assert decision["decision"] == "blocked"
        assert decision["activation_permitted"] is False
        inactive = all(
            _find_skill(name) is None
            for name in ("invoice-organizer", "poisoned-invoice-organizer")
        )
        preserved = all(path.exists() for path in pending_paths.values())
        assert inactive and preserved
        rejection = reject_pending(store, review_id, hermes_home=home)
        assert not pending_paths["candidate"].exists()
        assert pending_paths["baseline"].exists()
        assert _find_skill("poisoned-invoice-organizer") is None
        report = {
            "run_id": run_id,
            "reviews": reviews,
            "decision": decision,
            "native_gate_enabled": True,
            "active_skills_absent": inactive,
            "pending_preserved": preserved,
            "fake_canary_received": checks["fake_canary_received"],
            "scope": "Real Hermes tool staging; controlled script replay, no full agent session",
            "sandbox": sandbox,
            "image": "python:3.12-slim",
            "model_explanation_live": args.live_explanation,
            "baseline_decision": baseline_decision,
            "policy_draft": policy,
            "static_statuses": {
                kind: store.get(rid)["latest"]["static"]["overall_status"]
                for kind, rid in reviews.items()
            },
            "rejection": rejection,
            "baseline_pending_preserved": pending_paths["baseline"].exists(),
        }
        (run / "integration.json").write_text(json.dumps(report, indent=2) + "\n")
        (root / "results/integration-latest.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        reset_hermes_home_override(token)
        if created:
            command(["openshell", "sandbox", "stop", sandbox], run / "sandbox-stop.txt")


if __name__ == "__main__":
    # Scanner subprocesses need the pinned environment's executables on PATH.
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    main()
