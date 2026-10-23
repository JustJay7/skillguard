"""Reconstruct proposed mutations using Hermes in a disposable profile.

This performs native text/file mutations, never executes candidate scripts, and
never calls the approval bypass against the user's active profile.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from skillguard.intercept.pending import PendingSkillWrite
from skillguard.review.snapshot import snapshot_digest

HERMES_PIN = "a9a54245b2311c705d29050b7f9868c015917aec"
APPLY = """
import json, sys
from pathlib import Path
from hermes_constants import get_hermes_home
from tools.skill_manager_tool import apply_skill_pending
profile = Path.cwd().resolve()
assert get_hermes_home().resolve() == profile
print(apply_skill_pending(json.loads(sys.stdin.read())))
"""


def checked_mutation(candidate: PendingSkillWrite) -> dict:
    if candidate.is_creation:
        raise ValueError("existing-skill reconstruction does not accept creates")
    payload = candidate.payload
    ops = payload["operations"] if candidate.action == "batch" else [payload]
    for op in ops:
        action = op.get("action")
        if action not in {"edit", "patch", "write_file", "remove_file"}:
            raise ValueError("unsupported mutation; deletion remains held")
        if op.get("name") != candidate.name:
            raise ValueError("mutation must target one skill")
        path = op.get("file_path")
        if path is not None and path != "SKILL.md":
            parts = path.split("/") if isinstance(path, str) else []
            if (
                len(parts) < 2
                or parts[0] not in {"scripts", "references", "templates", "assets"}
                or any(part in {"", ".", ".."} for part in parts)
                or any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in parts)
            ):
                raise ValueError("unsafe mutation file path")
        if action == "remove_file" and path == "SKILL.md":
            raise ValueError("removing SKILL.md remains held")
        if action in {"write_file", "remove_file"} and path is None:
            raise ValueError("supporting file mutation requires a path")
    return payload


class HermesReconstructor:
    def __init__(self, source: Path) -> None:
        self.source = source.resolve()
        head = subprocess.run(
            ["git", "-C", str(self.source), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(self.source), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if head != HERMES_PIN or dirty:
            raise ValueError("Hermes source must match the unchanged recorded pin")

    def __call__(self, profile: Path, payload: dict) -> dict:
        temporary = profile / "tmp"
        temporary.mkdir()
        result = subprocess.run(
            [sys.executable, "-c", APPLY],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            cwd=profile,
            timeout=60,
            env={
                "HOME": str(profile),
                "HERMES_HOME": str(profile),
                "TMPDIR": str(temporary),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": str(self.source),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        if result.returncode:
            raise RuntimeError("native Hermes reconstruction failed; candidate remains held")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("native Hermes returned invalid reconstruction evidence") from error


def reconstruct_mutation(
    candidate: PendingSkillWrite,
    baseline: Path,
    destination: Path,
    native_apply: Callable[[Path, dict], dict],
) -> tuple[Path, Path, dict]:
    payload = checked_mutation(candidate)
    base_sha = snapshot_digest(baseline)
    with tempfile.TemporaryDirectory(prefix="sg-reconstruct-", dir=destination.parent) as temporary:
        profile = Path(temporary)
        copied = profile / "skills" / candidate.name
        shutil.copytree(baseline, copied)
        if snapshot_digest(copied) != base_sha or snapshot_digest(baseline) != base_sha:
            raise ValueError("installed baseline changed during capture")
        (profile / "config.yaml").write_text("skills:\n  write_approval: true\n")
        result = native_apply(profile, payload)
        if result.get("success") is not True or result.get("staged"):
            raise ValueError("native Hermes rejected reconstruction; candidate remains held")
        snapshot_digest(copied)
        if snapshot_digest(baseline) != base_sha:
            raise ValueError("installed baseline changed during reconstruction")
        destination.mkdir(exist_ok=False)
        archived_base = destination / "baseline" / candidate.name
        snapshot = destination / "candidate" / candidate.name
        shutil.copytree(baseline, archived_base)
        shutil.copytree(copied, snapshot)
        if snapshot_digest(archived_base) != base_sha:
            raise ValueError("installed baseline changed during archival")
        (snapshot.parent / "pending.json").write_bytes(candidate.raw)
        return snapshot, archived_base, result
