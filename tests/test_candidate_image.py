import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.learned_candidate_image import candidate_payload, guest_image_source
from skillguard.review.snapshot import digest, snapshot_digest


def setup(root, monkeypatch):
    run = root / "results/integration/local-parser-fixture"
    candidate = run / "candidate"
    (candidate / "scripts").mkdir(parents=True)
    (candidate / "SKILL.md").write_text("known guide fixture")
    parent = digest(json.dumps({"SKILL.md": digest((candidate / "SKILL.md").read_bytes())},
                               sort_keys=True).encode())
    monkeypatch.setattr("scripts.learned_candidate_image.LEARNED_SHA", parent)
    (candidate / "scripts/parse_receipt.py").write_text("print('fixture')")
    identity = snapshot_digest(candidate)
    review = {
        "snapshot": str(candidate),
        "candidate_sha256": identity,
        "latest": {"static": {"overall_status": "passed", "incomplete_scans": []}},
    }
    monkeypatch.setattr(
        "scripts.learned_candidate_image.ReviewStore",
        lambda _path: SimpleNamespace(get=lambda _id: review),
    )
    prep = run / "preparation.json"
    prep.write_text(
        json.dumps(
            {
                "parent_candidate_sha256": parent,
                "preparation_passed": True,
                "store": str(run / "reviews"),
                "review_id": "fixture",
                "candidate_sha256": identity,
                "parser_sha256": digest((candidate / "scripts/parse_receipt.py").read_bytes()),
            }
        )
    )
    return prep, candidate


def test_relative_cli_preparation_preserves_actual_candidate_identity(tmp_path, monkeypatch):
    prep, candidate = setup(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    payload = candidate_payload(Path.cwd(), prep.relative_to(tmp_path))
    assert payload["candidate_sha256"] == snapshot_digest(candidate)
    compile(guest_image_source(payload), "fixed native image setup", "exec")


def test_changed_prepared_source_is_refused_before_image_build(tmp_path, monkeypatch):
    prep, candidate = setup(tmp_path, monkeypatch)
    (candidate / "scripts/parse_receipt.py").write_text("print('changed')")
    with pytest.raises(ValueError, match="changed"):
        candidate_payload(tmp_path, prep)


def test_external_preparation_path_cannot_be_loaded(tmp_path):
    with pytest.raises(ValueError, match="archived local"):
        candidate_payload(tmp_path, tmp_path / "outside.json")


def test_parent_guide_bytes_must_match_declared_parent(tmp_path, monkeypatch):
    prep, candidate = setup(tmp_path, monkeypatch)
    (candidate / "SKILL.md").write_text("changed guide")
    with pytest.raises(ValueError, match="parent guide"):
        candidate_payload(tmp_path, prep)
