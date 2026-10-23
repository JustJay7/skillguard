from pathlib import Path

import pytest

from skillguard.intercept.rollback import rollback_operations


def skill(root: Path, content: str):
    root.mkdir()
    (root / "SKILL.md").write_text(content)
    (root / "scripts").mkdir()
    return root


def test_rollback_restores_old_content_and_removes_added_files(tmp_path):
    current = skill(tmp_path / "current", "proposed")
    target = skill(tmp_path / "target", "installed")
    (current / "scripts/added.py").write_text("added")
    (current / "scripts/existing.py").write_text("changed")
    (target / "scripts/existing.py").write_text("old")
    ops = rollback_operations("receipts", current, target)
    assert ops == [
        {"action": "patch", "name": "receipts", "content": "installed"},
        {
            "action": "write_file",
            "name": "receipts",
            "file_path": "scripts/existing.py",
            "file_content": "old",
        },
        {"action": "remove_file", "name": "receipts", "file_path": "scripts/added.py"},
    ]
    assert (current / "SKILL.md").read_text() == "proposed"


def test_matching_rollback_is_rejected(tmp_path):
    current = skill(tmp_path / "current", "installed")
    target = skill(tmp_path / "target", "installed")
    with pytest.raises(ValueError, match="already matches"):
        rollback_operations("receipts", current, target)


def test_binary_or_unsafe_rollback_is_held(tmp_path):
    current = skill(tmp_path / "current", "proposed")
    target = skill(tmp_path / "target", "installed")
    (target / "scripts/image.bin").write_bytes(b"\xff\xfe")
    with pytest.raises(UnicodeDecodeError):
        rollback_operations("receipts", current, target)
