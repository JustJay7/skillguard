from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SkillEvaluatorResult:
    report_path: Path
    report: dict[str, Any]
    stdout: str
    stderr: str
    returncode: int


class SkillEvaluatorRunner:
    """Thin wrapper around NVIDIA SkillEvaluator's documented CLI surface.

    The command shape is pinned to NVIDIA/SkillEvaluator commit
    33eb9dc74a09280bebf6fb4c921d290a0f874713.
    """

    def __init__(self, *, binary: str = "skillevaluator") -> None:
        self.binary = binary

    def tier1_command(self, skill_path: Path, output_dir: Path) -> list[str]:
        return [
            self.binary,
            "validate",
            str(skill_path),
            "--tiers",
            "1",
            "--no-llm",
            "-r",
            "json",
            "-o",
            str(output_dir),
        ]

    def run_tier1(self, skill_path: Path, output_dir: Path) -> SkillEvaluatorResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        run_dir = Path(tempfile.mkdtemp(prefix="tier1-", dir=output_dir))
        result = subprocess.run(
            self.tier1_command(skill_path, run_dir),
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(f"SkillEvaluator execution failed (exit {result.returncode})")
        candidates = sorted(run_dir.glob("skillevaluator-output-*.json"))
        if not candidates:
            raise RuntimeError("SkillEvaluator produced no JSON report")
        if len(candidates) != 1:
            raise RuntimeError("SkillEvaluator produced ambiguous JSON reports")
        report_path = candidates[-1]
        payload = json.loads(report_path.read_text())
        if not isinstance(payload, dict):
            raise RuntimeError("SkillEvaluator JSON report must be an object")
        return SkillEvaluatorResult(
            report_path=report_path,
            report=payload,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )
