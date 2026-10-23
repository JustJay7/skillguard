"""Read Hermes staged writes without approving them or touching active skills.

Creates can be materialized directly. Existing-skill changes require a captured
baseline and the pinned native Hermes mutation implementation.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class PendingSkillWrite:
    pending_id: str
    name: str
    action: str
    content: str | None
    raw: bytes
    files: tuple[tuple[str, str], ...] = ()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    @property
    def payload(self) -> dict:
        return json.loads(self.raw.decode("utf-8-sig"))["payload"]

    @property
    def is_creation(self) -> bool:
        return self.action == "create" or (
            self.action == "batch" and self.payload["operations"][0]["action"] == "create"
        )

    @classmethod
    def load(cls, path: Path) -> PendingSkillWrite:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict) or data.get("subsystem") != "skills":
            raise ValueError("expected a Hermes skills pending record")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("expected a pending payload object")
        action = payload.get("action")
        if action not in {
            "create",
            "edit",
            "patch",
            "delete",
            "write_file",
            "remove_file",
            "batch",
        }:
            raise ValueError("unsupported skill action")
        if action != data.get("action"):
            raise ValueError("record and payload action disagree")
        files = ()
        if action == "batch":
            ops = payload.get("operations")
            if isinstance(ops, list) and ops and isinstance(ops[0], dict):
                if ops[0].get("action") == "create":
                    payload, files = _creation_batch(payload)
                else:
                    payload = _mutation_batch(payload)
            else:
                raise ValueError("batch requires operations")
        name, pending_id = payload.get("name"), data.get("id")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", name):
            raise ValueError("unsafe or unsupported skill name")
        if not isinstance(pending_id, str) or not re.fullmatch(r"[0-9a-f]{8}", pending_id):
            raise ValueError("unsupported pending id")
        content = payload.get("content")
        if (action == "create" or files or payload.get("action") == "create") and not isinstance(
            content, str
        ):
            raise ValueError("create requires text content")
        return cls(pending_id, name, action, content, raw, files)

    def materialize_create(self, quarantine: Path) -> Path:
        """Create an immutable-by-convention snapshot; never replace an existing one.

        The quarantine directory must be operator-owned and outside Hermes' active
        skills directory. This is staging, not an execution sandbox or approval.
        """
        if not self.is_creation:
            raise ValueError("only create candidates can be materialized")
        destination = quarantine / f"{self.pending_id}-{self.sha256}" / self.name
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "SKILL.md").write_text(self.content, encoding="utf-8")
        for relative, content in self.files:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        (destination.parent / "pending.json").write_bytes(self.raw)
        return destination


def _mutation_batch(payload: dict) -> dict:
    operations = payload["operations"]
    name = operations[0].get("name")
    for op in operations:
        if not isinstance(op, dict) or op.get("action") not in {
            "patch",
            "edit",
            "write_file",
            "remove_file",
        }:
            raise ValueError("unsupported existing-skill batch action")
        if op.get("name") != name:
            raise ValueError("batch must target one skill")
    return operations[0]


def _creation_batch(payload: dict) -> tuple[dict, tuple[tuple[str, str], ...]]:
    """Support one new skill plus new files; never silently omit an operation."""
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("batch requires operations")
    first = operations[0]
    if not isinstance(first, dict) or first.get("action") != "create":
        raise ValueError("batch must start with create")
    files: dict[str, str] = {}
    for op in operations[1:]:
        if not isinstance(op, dict) or op.get("action") != "write_file":
            raise ValueError("only create followed by write_file is supported")
        if op.get("name") != first.get("name"):
            raise ValueError("batch must target one skill")
        path, content = op.get("file_path"), op.get("file_content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise ValueError("supporting file requires text path and content")
        parts = path.split("/")
        if (
            len(parts) < 2
            or parts[0] not in {"scripts", "references", "templates", "assets"}
            or any(part in {"", ".", ".."} for part in parts)
            or any(not re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in parts)
            or "\\" in path
            or "\x00" in path
        ):
            raise ValueError("unsafe supporting file path")
        candidate = PurePosixPath(path.casefold())
        if any(
            candidate == PurePosixPath(other.casefold())
            or candidate in PurePosixPath(other.casefold()).parents
            or PurePosixPath(other.casefold()) in candidate.parents
            for other in files
        ):
            raise ValueError("duplicate or conflicting supporting file paths")
        files[path] = content
    return first, tuple(files.items())
