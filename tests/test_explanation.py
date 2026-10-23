import json
from pathlib import Path

import pytest

from skillguard.models.explanation import parse_explanation


def recorded_response() -> dict:
    response = json.loads(Path("tests/fixtures/nemotron_receipt_response.json").read_text())
    return json.loads(response["choices"][0]["message"]["content"])


def test_recorded_nemotron_response_has_valid_evidence_references() -> None:
    advice = parse_explanation(json.dumps(recorded_response()), dict.fromkeys(["E1", "E2", "E3"]))
    assert advice.recommendation == "block"
    assert advice.evidence_ids


@pytest.mark.parametrize(
    "changes",
    [
        {"evidence_ids": ["invented-event"]},
        {"evidence_ids": []},
        {"evidence_ids": "E1"},
        {"evidence_ids": [None]},
        {"recommendation": "activate-immediately"},
        {"explanation": ""},
        {"activation": "approved"},
    ],
)
def test_unusable_or_untrusted_model_fields_are_rejected(changes: dict) -> None:
    content = recorded_response() | changes
    with pytest.raises(ValueError):
        parse_explanation(json.dumps(content), dict.fromkeys(["E1", "E2", "E3"]))
