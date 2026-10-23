"""Freeze operator-authored local cases before native text-only parser repair."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from skillguard.review.snapshot import digest


def validate_suite(raw: bytes) -> dict:
    data = json.loads(raw)
    cases = data.get("cases")
    if not isinstance(cases, dict) or not cases:
        raise ValueError("Missing receipt contract cases")
    from skillguard.evaluation.receipt_grader import grade_payloads

    grade_payloads({}, {name: case["expected"] for name, case in cases.items()})
    keys = {"date", "vendor", "subtotal", "tax", "total", "needs_clarification"}
    if any(not isinstance(c["input"], str) or set(c["expected"]) != keys for c in cases.values()):
        raise ValueError("Invalid receipt input or output schema")
    return cases


def load_frozen(manifest: Path) -> tuple[dict, dict]:
    data = json.loads(manifest.read_text())
    suites = []
    for name in ("development", "heldout"):
        raw = (manifest.parent / f"{name}.json").read_bytes()
        if digest(raw) != data["suite_sha256"][name]:
            raise ValueError("Frozen receipt contract changed")
        suites.append(validate_suite(raw))
    if set(suites[0]) & set(suites[1]):
        raise ValueError("Development and held-out cases overlap")
    return tuple(suites)


def freeze(root: Path) -> Path:
    folder = root / "results/integration" / f"receipt-contract-{uuid.uuid4().hex[:8]}"
    folder.mkdir(mode=0o700)
    hashes = {}
    for name in ("development", "heldout"):
        raw = (root / f"config/receipt-contracts/{name}.json").read_bytes()
        validate_suite(raw)
        path = folder / f"{name}.json"
        path.write_bytes(raw)
        path.chmod(0o400)
        hashes[name] = digest(raw)
    manifest = folder / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "frozen_at": datetime.now(UTC).isoformat(),
                "suite_sha256": hashes,
                "scope": "Authored local domain checks; no generated attack claims",
                "repair_receives_test_inputs": False,
                "heldout_feedback_to_repair": False,
            },
            indent=2,
        )
        + "\n"
    )
    manifest.chmod(0o400)
    load_frozen(manifest)
    return manifest


def seal_heldout(manifest: Path, candidate_sha256: str) -> None:
    """Persist that the final candidate was chosen before unseen evaluation."""
    import re

    if not re.fullmatch(r"[a-f0-9]{64}", candidate_sha256):
        raise ValueError("Invalid candidate identity for unseen evaluation")
    load_frozen(manifest)
    path = manifest.parent / "heldout-release.json"
    data = {"candidate_sha256": candidate_sha256, "manifest_sha256": digest(manifest.read_bytes()),
            "released_at": datetime.now(UTC).isoformat(), "further_repair_allowed": False}
    if path.exists():
        previous = json.loads(path.read_text())
        if any(previous.get(k) != data[k] for k in ("candidate_sha256", "manifest_sha256")):
            raise ValueError("Unseen suite already released to a different candidate")
        return
    with path.open("x") as stream:
        stream.write(json.dumps(data, indent=2) + "\n")
    path.chmod(0o400)


def ensure_repair_unreleased(manifest: Path) -> None:
    load_frozen(manifest)
    if (manifest.parent / "heldout-release.json").exists():
        raise ValueError("Unseen suite released; further repair requires a new contract")
