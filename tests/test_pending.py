import json
from pathlib import Path

import pytest

from skillguard.intercept.pending import PendingSkillWrite


def record():
    return {
        "id": "abcdef12",
        "subsystem": "skills",
        "action": "create",
        "summary": "create invoice",
        "origin": "foreground",
        "created_at": 1.0,
        "payload": {"action": "create", "name": "invoice", "content": "# Invoice\n"},
    }


def test_capture_preserves_pending_and_never_activates(tmp_path):
    pending = tmp_path / "pending.json"
    pending.write_text(json.dumps(record()))
    candidate = PendingSkillWrite.load(pending)
    destination = candidate.materialize_create(tmp_path / "quarantine")
    assert (destination / "SKILL.md").read_text() == "# Invoice\n"
    assert json.loads(pending.read_text()) == record()
    assert not (tmp_path / "skills").exists()
    assert len(candidate.sha256) == 64
    with pytest.raises(FileExistsError):
        candidate.materialize_create(tmp_path / "quarantine")


@pytest.mark.parametrize("name", ["../escape", "/tmp/escape", "a/b", "", ".", ".."])
def test_reject_unsafe_skill_names(tmp_path, name):
    data = record()
    data["payload"]["name"] = name
    path = tmp_path / "record.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        PendingSkillWrite.load(path)


def test_non_create_requires_full_candidate_reconstruction(tmp_path):
    data = record()
    data["action"] = data["payload"]["action"] = "patch"
    path = tmp_path / "record.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="create"):
        PendingSkillWrite.load(path).materialize_create(tmp_path / "quarantine")


def test_reject_mismatched_record(tmp_path: Path):
    data = record()
    data["action"] = "delete"
    path = tmp_path / "record.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="action"):
        PendingSkillWrite.load(path)


def batch_record(path="scripts/run.py", action="write_file", name="invoice"):
    data = record()
    data["action"] = "batch"
    data["payload"] = {
        "action": "batch",
        "operations": [
            {"action": "create", "name": "invoice", "content": "# Invoice\n"},
            {"action": action, "name": name, "file_path": path, "file_content": "print('ok')\n"},
        ],
    }
    return data


def test_materialize_creation_batch_with_supporting_script(tmp_path):
    pending = tmp_path / "record.json"
    pending.write_text(json.dumps(batch_record()))
    candidate = PendingSkillWrite.load(pending)
    skill = candidate.materialize_create(tmp_path / "quarantine")
    assert (skill / "scripts/run.py").read_text() == "print('ok')\n"
    assert (skill / "SKILL.md").read_text() == "# Invoice\n"
    assert pending.is_file()


@pytest.mark.parametrize(
    "path",
    [
        "../escape.py",
        "/tmp/escape.py",
        "scripts/../../escape.py",
        "scripts/../SKILL.md",
        "scripts//x.py",
        "scripts\\x.py",
        "SKILL.md",
        "scripts/./x.py",
        "scripts",
        "scripts/",
        "scripts/\x00x.py",
    ],
)
def test_batch_rejects_unsafe_support_paths_before_writing(tmp_path, path):
    pending = tmp_path / "record.json"
    pending.write_text(json.dumps(batch_record(path=path)))
    with pytest.raises(ValueError):
        PendingSkillWrite.load(pending).materialize_create(tmp_path / "quarantine")
    assert not (tmp_path / "quarantine").exists()


@pytest.mark.parametrize("change", ["other_skill", "patch", "duplicate", "empty"])
def test_batch_rejects_unsupported_mutations(tmp_path, change):
    data = batch_record()
    ops = data["payload"]["operations"]
    if change == "other_skill":
        ops[-1]["name"] = "other"
    elif change == "patch":
        ops[-1]["action"] = "patch"
    elif change == "duplicate":
        ops.append(ops[-1].copy())
    else:
        ops.clear()
    pending = tmp_path / "record.json"
    pending.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        PendingSkillWrite.load(pending).materialize_create(tmp_path / "quarantine")
    assert not (tmp_path / "quarantine").exists()


@pytest.mark.parametrize("other", ["scripts/RUN.py", "scripts/run.py/child"])
def test_reject_cross_platform_file_collisions(tmp_path, other):
    data = batch_record()
    extra = data["payload"]["operations"][-1].copy()
    extra["file_path"] = other
    data["payload"]["operations"].append(extra)
    pending = tmp_path / "record.json"
    pending.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        PendingSkillWrite.load(pending)
