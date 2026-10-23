import json
from pathlib import Path

import pytest

from skillguard.evaluation.skillevaluator import SkillEvaluatorRunner


def test_tier1_command_matches_pinned_cli_contract(tmp_path: Path) -> None:
    runner = SkillEvaluatorRunner(binary="skillevaluator")
    command = runner.tier1_command(Path("skills/demo"), tmp_path)

    assert command == [
        "skillevaluator",
        "validate",
        "skills/demo",
        "--tiers",
        "1",
        "--no-llm",
        "-r",
        "json",
        "-o",
        str(tmp_path),
    ]


def test_run_tier1_returns_machine_report(monkeypatch, tmp_path: Path) -> None:
    runner = SkillEvaluatorRunner(binary="skillevaluator")

    def fake_run(command, check, capture_output, text, timeout):
        assert command[0] == "skillevaluator"
        report = Path(command[-1]) / "skillevaluator-output-20260929200000.json"
        report.write_text(json.dumps({"status": "passed", "score": 91}))

        class Result:
            stdout = ""
            stderr = ""
            returncode = 0

        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)
    result = runner.run_tier1(Path("skills/demo"), tmp_path)

    assert result.report_path.name.startswith("skillevaluator-output-")
    assert result.report == {"status": "passed", "score": 91}


def test_validation_failure_preserves_incomplete_report(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        assert kwargs["check"] is False
        report = Path(command[-1]) / "skillevaluator-output-test.json"
        report.write_text(json.dumps({"overall_passed": False, "overall_status": "incomplete"}))
        from subprocess import CompletedProcess

        return CompletedProcess(command, 1, "", "validation failed")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = SkillEvaluatorRunner().run_tier1(Path("skills/demo"), tmp_path)
    assert result.returncode == 1
    assert result.report["overall_status"] == "incomplete"


def test_never_reuses_stale_passing_report(monkeypatch, tmp_path):
    (tmp_path / "skillevaluator-output-old.json").write_text('{"overall_passed": true}')

    def fake_run(command, **kwargs):
        from subprocess import CompletedProcess

        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="no JSON report"):
        SkillEvaluatorRunner().run_tier1(Path("skills/demo"), tmp_path)
