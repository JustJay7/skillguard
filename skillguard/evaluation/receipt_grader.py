"""Domain-specific BYOT grader, executed by native Harbor after the frozen parser.

Only checks fictional local outputs. These checks do not establish telemetry
completeness, model instruction resistance, or safe activation.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


def grade_outputs(output: Path, expectations: dict) -> dict:
    if any(not re.fullmatch(r"[a-z0-9_]{1,40}", name) for name in expectations):
        raise ValueError("Unsafe contract case name")
    outputs = {}
    for name in expectations:
        try:
            outputs[name] = (output / f"{name}.json").read_text()
        except OSError:
            outputs[name] = None
    return grade_payloads(outputs, expectations)


def grade_payloads(outputs: dict, expectations: dict) -> dict:
    checks = {}
    for name, expected in expectations.items():
        try:
            actual = json.loads(outputs.get(name))
            # Reject bools for numeric amounts and unexpected keys as well as values.
            passed = isinstance(actual, dict) and actual.keys() == expected.keys() and all(
                (type(actual[key]) in (int, float) if type(value) in (int, float)
                 else type(actual[key]) is type(value)) and actual[key] == value
                for key, value in expected.items()
            )
            checks[name] = {"score": float(passed), "reason": "match" if passed else "mismatch"}
        except (ValueError, TypeError):
            checks[name] = {"score": 0.0, "reason": "missing or invalid output"}
    if not checks:
        raise ValueError("No domain expectations supplied")
    # Every authored contract case must pass; no averaging hides a failure.
    overall = float(all(item["score"] == 1.0 for item in checks.values()))
    return {"overall": overall, "custom_metrics": {
        name: item["score"] for name, item in checks.items()
    }, "details": checks}


def main() -> None:
    tests = Path(os.environ.get("HARBOR_TESTS_DIR", "/tests"))
    expected = json.loads((tests / "expectations.json").read_text())
    result = grade_outputs(Path("/workspace/out"), expected)
    target = Path(os.environ.get("HARBOR_REWARD_JSON", "/logs/verifier/reward.json"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n")
    Path(os.environ.get("HARBOR_REWARD_TXT", "/logs/verifier/reward.txt")).write_text(
        str(result["overall"]) + "\n"
    )


if __name__ == "__main__":
    main()
