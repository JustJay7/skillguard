from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_digest(root: Path) -> str:
    if root.is_symlink() or not root.is_dir() or not (root / "SKILL.md").is_file():
        raise ValueError("snapshot requires a regular skill directory with SKILL.md")
    return artifact_tree_digest(root)


def artifact_tree_digest(root: Path) -> str:
    """Bind operator-owned artifact trees with the existing file manifest format."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("artifact tree requires a regular directory")
    files = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("snapshot contains a symlink or special file")
        if stat.S_ISREG(mode):
            files[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return digest(json.dumps(files, sort_keys=True).encode())
