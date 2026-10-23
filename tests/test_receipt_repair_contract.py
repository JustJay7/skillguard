import json
from pathlib import Path

import pytest

from scripts.freeze_receipt_contract import freeze, load_frozen


def fixture(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = tmp_path / "config/receipt-contracts"
    config.mkdir(parents=True)
    for name in ("development", "heldout"):
        (config / f"{name}.json").write_bytes(
            (root / f"config/receipt-contracts/{name}.json").read_bytes()
        )
    (tmp_path / "results/integration").mkdir(parents=True, exist_ok=True)
    return freeze(tmp_path)


def test_contract_is_frozen_before_repair_with_distinct_cases(tmp_path):
    manifest = fixture(tmp_path)
    development, heldout = load_frozen(manifest)
    assert len(development) == 4 and len(heldout) == 8
    assert not set(development) & set(heldout)
    assert json.loads(manifest.read_text())["repair_receives_test_inputs"] is False


def test_frozen_contract_changes_are_refused(tmp_path):
    manifest = fixture(tmp_path)
    path = manifest.parent / "heldout.json"
    path.chmod(0o600)
    path.write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        load_frozen(manifest)


def test_repair_prompt_never_contains_development_or_unseen_test_values(tmp_path):
    from scripts.hermes_local_parser_probe import repair_prompt

    manifest = fixture(tmp_path)
    development, heldout = load_frozen(manifest)
    prompt = repair_prompt("# old parser source")
    assert "# old parser source" in prompt
    for case in list(development.values()) + list(heldout.values()):
        if case["input"].strip():
            assert case["input"] not in prompt
    assert "role_spoof" not in prompt


def test_repair_prompt_cannot_include_receipt_values_from_old_trial(tmp_path):
    from scripts.hermes_local_parser_probe import repair_prompt

    assert "24.73" not in repair_prompt("pass\n")
    assert "Harbor Mock Grocery" not in repair_prompt("pass\n")


def test_releasing_unseen_tests_prevents_further_repair_and_candidate_switching(tmp_path):
    from skillguard.evaluation.receipt_contract import ensure_repair_unreleased, seal_heldout

    manifest = fixture(tmp_path)
    ensure_repair_unreleased(manifest)
    seal_heldout(manifest, "a" * 64)
    seal_heldout(manifest, "a" * 64)
    with pytest.raises(ValueError, match="further repair"):
        ensure_repair_unreleased(manifest)
    with pytest.raises(ValueError, match="different candidate"):
        seal_heldout(manifest, "b" * 64)
