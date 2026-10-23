from __future__ import annotations

from pathlib import PurePosixPath

from skillguard.envelope.schema import BehavioralEnvelope


def _path(value: str) -> str:
    if (
        not value.startswith("/")
        or value.startswith("//")
        or value == "/"
        or "\x00" in value
        or any(char in value for char in "*?[]\\")
        or str(PurePosixPath(value)) != value
        or ".." in PurePosixPath(value).parts
    ):
        raise ValueError("filesystem grants require normalized absolute literal paths")
    return value


def draft_policy(allowed: BehavioralEnvelope, *, runtime_read_only: list[str]) -> dict:
    """Draft a file-only OpenShell v0.1.2 policy from an operator contract.

    Runtime paths are separately supplied image prerequisites, never model-derived.
    Drafts are not applied: file-rule existence and effective denial must be tested
    in a freshly prepared sandbox before using them as enforcement evidence.
    """
    if allowed.network_hosts:
        raise ValueError(
            "network grants require verified binary/endpoints; unsupported in this draft"
        )
    if allowed.processes or allowed.tools:
        raise ValueError(
            "process/tool restrictions cannot be encoded by this file-only policy draft"
        )
    writable = {_path(path) for path in allowed.files_written} | {"/dev/null"}
    readonly = {_path(path) for path in allowed.files_read} | {
        _path(path) for path in runtime_read_only
    }
    return {
        "policy": {
            "version": 1,
            "filesystem_policy": {
                "include_workdir": False,
                "read_only": sorted(readonly - writable),
                "read_write": sorted(writable),
            },
            "landlock": {"compatibility": "hard_requirement"},
        },
        "applied": False,
        "scope": "sandbox",
        "source": "operator_contract",
        "limitations": [
            "Fresh-sandbox enforcement not verified",
            "Paths must exist in the prepared filesystem; no parent grants inferred",
            "Runtime read-only paths are image prerequisites with directory-wide access",
            "This policy does not implement a process allowlist or tool restrictions",
            "Landlock file rules do not restrict permission/ownership metadata changes",
        ],
    }
