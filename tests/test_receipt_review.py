import json
from pathlib import Path

from scripts.render_receipt_review import render


def test_untrusted_model_text_and_trace_paths_cannot_execute_in_review() -> None:
    response = json.loads(Path("tests/fixtures/nemotron_receipt_response.json").read_text())
    advice = json.loads(response["choices"][0]["message"]["content"])
    attack = '<script>alert("untrusted")</script>'
    review = {
        "evidence": {
            "E1": {
                "value": {
                    "added": {
                        "files_read": [attack],
                        "files_written": [],
                        "network_hosts": [],
                        "processes": [],
                        "tools": [],
                    },
                    "removed": {},
                }
            }
        },
        "model_recommendation": advice["recommendation"],
        "explanation": attack,
        "evidence_ids": advice["evidence_ids"],
        "model": response["model"],
        "estimated_cost_usd": 0,
    }
    document = render(review, [])
    assert "<script>" not in document
    assert "&lt;script&gt;" in document
    assert "Activation held" in document
