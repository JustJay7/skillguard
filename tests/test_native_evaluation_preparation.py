import json
import shutil
from pathlib import Path

import pytest

from scripts import prepare_native_evaluation as preparation
from skillguard.review.snapshot import artifact_tree_digest, digest, snapshot_digest


def test_tree_identity_changes_with_paths_and_rejects_links(tmp_path):
    (tmp_path / "a").write_text("same")
    before = artifact_tree_digest(tmp_path)
    (tmp_path / "a").rename(tmp_path / "b")
    assert artifact_tree_digest(tmp_path) != before
    (tmp_path / "link").symlink_to(tmp_path / "b")
    with pytest.raises(ValueError, match="symlink"):
        artifact_tree_digest(tmp_path)


def test_native_scaffold_passes_actual_harbor_schema(tmp_path, monkeypatch):
    pytest.importorskip("harbor")
    from harbor.models.task.task import Task

    root = Path(__file__).resolve().parents[1]
    if not (root / ".venv/bin/skillevaluator").is_file():
        pytest.skip("Optional pinned native evaluator is not installed")
    snapshot = tmp_path / "snapshot"
    (snapshot / "scripts").mkdir(parents=True)
    (snapshot / "SKILL.md").write_text(
        "---\nname: receipt-organizer\ndescription: Organize fictional local receipts.\n---\n"
        "Run scripts/parse_receipt.py locally.\n"
    )
    script = snapshot / "scripts/parse_receipt.py"
    script.write_text("pass\n")
    original = snapshot_digest(snapshot)
    monkeypatch.setattr(preparation, "KNOWN_CANDIDATE", original)
    monkeypatch.setattr(preparation, "KNOWN_PARSER", digest(script.read_bytes()))
    parent = tmp_path / "parent.json"
    parent.write_text(json.dumps({"snapshot": str(snapshot), "candidate_sha256": original,
                                 "parser_sha256": digest(script.read_bytes()),
                                 "review_id": "disposable", "store": str(tmp_path)}))
    # Native commands run only metadata generation/validation; pass source is never executed.
    disposable = tmp_path / "native-preparation"
    (disposable / "results/integration").mkdir(parents=True)
    (disposable / ".venv").symlink_to(root / ".venv", target_is_directory=True)
    grader = disposable / "skillguard/evaluation/receipt_grader.py"
    grader.parent.mkdir(parents=True)
    shutil.copyfile(root / "skillguard/evaluation/receipt_grader.py", grader)
    result = preparation.prepare(disposable, parent, publish_latest=False)
    task = Task(result["task"])
    assert task.config.environment.network_mode.value == "no-network"
    assert task.config.agent.user == "1000:1000"
    assert snapshot_digest(snapshot) == original
    assert result["execution"] == "not_started"
    assert result["activation_eligible"] is False
