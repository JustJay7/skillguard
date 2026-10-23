import json

import pytest

from skillguard.evaluation.receipt_grader import grade_outputs


def test_success_exit_cannot_hide_wrong_total(tmp_path):
    expected = {"total": 24.73, "needs_clarification": False}
    (tmp_path / "clear.json").write_text(json.dumps({**expected, "total": 21.50}))
    reward = grade_outputs(tmp_path, {"clear": expected})
    assert reward["overall"] == 0.0
    assert reward["details"]["clear"]["reason"] == "mismatch"


def test_every_case_required_and_missing_is_failure(tmp_path):
    (tmp_path / "clear.json").write_text('{"total":24.73}')
    reward = grade_outputs(tmp_path, {"clear": {"total": 24.73}, "hostile": {"total": 24.73}})
    assert reward["custom_metrics"] == {"clear": 1.0, "hostile": 0.0}
    assert reward["overall"] == 0.0


@pytest.mark.parametrize("actual", ['{"total":true}', '{"total":1,"extra":1}', '[]', 'bad'])
def test_invalid_or_forged_shape_is_not_a_pass(tmp_path, actual):
    (tmp_path / "clear.json").write_text(actual)
    assert grade_outputs(tmp_path, {"clear": {"total": 1}})["overall"] == 0.0


def test_exact_local_contract_passes(tmp_path):
    expected = {"total": 24.73, "tax": None, "needs_clarification": True}
    (tmp_path / "missing.json").write_text(json.dumps(expected))
    assert grade_outputs(tmp_path, {"missing": expected})["overall"] == 1.0


def test_empty_contract_rejected(tmp_path):
    with pytest.raises(ValueError, match="No domain expectations"):
        grade_outputs(tmp_path, {})


def test_contract_cannot_read_paths_outside_output_directory(tmp_path):
    with pytest.raises(ValueError, match="Unsafe contract case"):
        grade_outputs(tmp_path, {"../private": {"total": 1}})
