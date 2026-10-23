"""Compare native file enforcement with fake fixtures in two new local VMs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

from scripts.hermes_review_probe import command
from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.intercept.reconstruct import HermesReconstructor
from skillguard.review.store import ReviewStore

PROBE = """
import json, os
from pathlib import Path
root=Path('/sandbox/strict/bundle')
receipt=(root/'data/receipt.txt').read_text()
(root/'output/out.txt').write_text('processed:'+receipt)
result={'uid':os.getuid(), 'receipt_read':receipt=='invoice-42',
        'output_written':(root/'output/out.txt').read_text()=='processed:invoice-42',
        'private_mode':oct((root/'data/fake-private.txt').stat().st_mode & 0o777)}
try:
 result['private_read']=(root/'data/fake-private.txt').read_text()=='FAKE_CANARY_SECRET'
except OSError as error:
 result.update(private_read=False, private_errno=error.errno)
print(json.dumps(result))
"""
SKILL = """---
name: policy-receipt-probe
description: Controlled fake-data receipt file-policy test.
version: 0.1.0
metadata:
  author: SkillGuard Test Fixture <fixture@example.invalid>
---

# Policy Receipt Probe

Operator-controlled enforcement check using fake files only.
"""


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared-rootfs", type=Path, required=True)
    args = parser.parse_args()
    if not args.prepared_rootfs.is_file():
        parser.error("prepared rootfs archive does not exist")
    run_id = uuid.uuid4().hex[:8]
    run = root / "results/integration" / f"policy-{run_id}"
    run.mkdir(parents=True)
    source = root.parent / "work/hermes-agent"
    HermesReconstructor(source)  # Check the native staging implementation's pin.
    sys.path.insert(0, str(source))
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.skill_manager_tool import _find_skill, skill_manage
    from tools.write_approval import write_approval_enabled

    profile = run / "hermes-profile"
    profile.mkdir()
    (profile / "config.yaml").write_text("skills:\n  write_approval: true\n")
    token = set_hermes_home_override(profile)
    try:
        assert write_approval_enabled("skills")
        staged = json.loads(
            skill_manage(
                action="",
                name="",
                operations=[
                    {
                        "action": "create",
                        "name": "policy-receipt-probe",
                        "content": SKILL,
                    },
                    {
                        "action": "write_file",
                        "name": "policy-receipt-probe",
                        "file_path": "scripts/probe.py",
                        "file_content": PROBE,
                    },
                ],
            )
        )
        assert staged.get("staged") is True, staged
        assert _find_skill("policy-receipt-probe") is None
        pending = profile / "pending/skills" / f"{staged['pending_id']}.json"
        store = ReviewStore(run / "reviews")
        review_id = store.capture(pending)
    finally:
        reset_hermes_home_override(token)
    contract = BehavioralEnvelope(
        files_read=["/sandbox/strict/bundle/data/receipt.txt"],
        files_written=["/sandbox/strict/bundle/output/out.txt"],
    )
    runtime = json.loads((root / "results/openshell-policy.json").read_text())["policy"]
    store.record_contract(review_id, contract)
    draft = store.record_policy_draft(
        review_id, runtime_read_only=runtime["filesystem_policy"]["read_only"]
    )["data"]
    policy = run / "policy.json"
    policy.write_text(json.dumps(draft["policy"], indent=2) + "\n")
    outcomes = {}
    for restricted in (False, True):
        kind = "restricted" if restricted else "permissive"
        sandbox = f"sg-{'r' if restricted else 'p'}-{run_id}"
        create = [
            "openshell",
            "sandbox",
            "create",
            "--name",
            sandbox,
            "--from",
            str(args.prepared_rootfs.resolve()),
            "--detach",
            "--no-auto-providers",
        ]
        if restricted:
            create += ["--policy", str(policy)]
        created = False
        try:
            command(create + ["--", "sleep", "3600"], run / f"{kind}-create.txt")
            created = True
            review = store.get(review_id)
            executed_source = (Path(review["snapshot"]) / "scripts/probe.py").read_text()
            command(
                [
                    "openshell",
                    "sandbox",
                    "exec",
                    "-n",
                    sandbox,
                    "--no-login-shell",
                    "--",
                    "python",
                    "-c",
                    executed_source,
                ],
                run / f"{kind}-probe.txt",
            )
            store.get(review_id)
            outcomes[kind] = json.loads((run / f"{kind}-probe.txt").read_text())
            command(
                ["openshell", "sandbox", "get", sandbox, "-o", "json"], run / f"{kind}-native.json"
            )
        finally:
            if created:
                command(["openshell", "sandbox", "stop", sandbox], run / f"{kind}-stop.txt")
    assert outcomes["permissive"]["private_read"] is True
    assert outcomes["restricted"]["private_read"] is False
    assert outcomes["restricted"]["private_errno"] == 13
    assert all(value["receipt_read"] and value["output_written"] for value in outcomes.values())
    assert outcomes["permissive"]["private_mode"] == outcomes["restricted"]["private_mode"]
    with args.prepared_rootfs.open("rb") as archive:
        rootfs_sha = hashlib.file_digest(archive, "sha256").hexdigest()
    captured = store.get(review_id)
    enforcement = store.record_file_enforcement(
        review_id,
        executed_candidate_sha256=captured["candidate_sha256"],
        rootfs_sha256=rootfs_sha,
        native_policy=(run / "restricted-native.json").read_bytes(),
        permissive_result=(run / "permissive-probe.txt").read_bytes(),
        restricted_result=(run / "restricted-probe.txt").read_bytes(),
    )
    assert pending.is_file()
    assert not (profile / "skills/policy-receipt-probe/SKILL.md").exists()
    report = {
        "run_id": run_id,
        "rootfs_sha256": rootfs_sha,
        "review_id": review_id,
        "candidate_sha256": captured["candidate_sha256"],
        "file_enforcement": enforcement["data"],
        "decision": store.decide(review_id),
        "pending_preserved": True,
        "active_skill_absent": True,
        "outcomes": outcomes,
        "policy": draft["policy"],
        "contract": contract.to_dict(),
        "scope": "Fake-data file-only enforcement probe; "
        "not a complete runtime trace or network enforcement test",
    }
    (run / "enforcement.json").write_text(json.dumps(report, indent=2) + "\n")
    (root / "results/policy-enforcement-latest.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
