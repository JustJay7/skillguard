"""Exercise real upstream Hermes in a temporary profile, without a model call.

Usage: PYTHONPATH=/path/to/pinned/hermes-agent python -m scripts.hermes_staging_probe
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from skillguard.intercept.pending import PendingSkillWrite


def main() -> None:
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    root = Path(__file__).resolve().parents[1]
    content = (root / "skills/benign/invoice-organizer/SKILL.md").read_text()
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary)
        (home / "config.yaml").write_text("skills:\n  write_approval: true\n")
        token = set_hermes_home_override(home)
        try:
            from tools.skill_manager_tool import _find_skill, skill_manage
            from tools.write_approval import write_approval_enabled

            assert write_approval_enabled("skills"), "Hermes gate did not enable"
            result = json.loads(
                skill_manage(
                    action="create",
                    name="invoice-organizer",
                    content=content,
                )
            )
            assert result.get("staged") is True, result
            pending = home / "pending/skills" / f"{result['pending_id']}.json"
            assert pending.is_file()
            assert _find_skill("invoice-organizer") is None
            candidate = PendingSkillWrite.load(pending)
            materialized = candidate.materialize_create(home / "quarantine")
            assert (materialized / "SKILL.md").read_text() == content
            assert pending.is_file()
            assert _find_skill("invoice-organizer") is None
            batch = json.loads(
                skill_manage(
                    action="",
                    name="",
                    operations=[
                        {
                            "action": "create",
                            "name": "batch-invoice",
                            "content": content,
                        },
                        {
                            "action": "write_file",
                            "name": "batch-invoice",
                            "file_path": "scripts/run.py",
                            "file_content": "print('fake invoice')\n",
                        },
                    ],
                )
            )
            assert batch.get("staged") is True, batch
            batch_path = home / "pending/skills" / f"{batch['pending_id']}.json"
            batch_candidate = PendingSkillWrite.load(batch_path)
            batch_skill = batch_candidate.materialize_create(home / "quarantine")
            assert (batch_skill / "scripts/run.py").read_text() == "print('fake invoice')\n"
            assert _find_skill("batch-invoice") is None
            assert batch_path.is_file()
            evidence = {
                "gate_enabled": True,
                "flat_write_staged": True,
                "candidate_materialized": True,
                "active_skill_absent": True,
                "pending_preserved": True,
                "candidate_sha256": candidate.sha256,
                "batch_write_staged": True,
                "batch_supporting_file_materialized": True,
                "scope": "Real skill_manage call; no LLM or full agent session",
            }
            (root / "results/hermes_staging.json").write_text(json.dumps(evidence, indent=2) + "\n")
            print(json.dumps(evidence, indent=2))
        finally:
            reset_hermes_home_override(token)


if __name__ == "__main__":
    main()
