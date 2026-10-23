import copy
import json
import sys

import pytest

from skillguard.review.snapshot import digest


def test_file_trial_requires_current_passing_candidate_and_policy():
    from scripts.linux_receipt_policy_probe import validate_trial

    contract = {"allowed": {"files_read": ["/input"]}}
    review = {"candidate_sha256": "a" * 64, "latest": {
        "contract": contract,
        "policy_draft": {"candidate_sha256": "a" * 64,
            "contract_sha256": digest(json.dumps(contract, sort_keys=True).encode()),
            "policy": {"version": 1}},
        "candidate_execution": {"candidate_sha256": "a" * 64,
            "image_id": "sha256:" + "b" * 64, "functional_passed": True, "failure_reasons": []},
        "frozen_resource_evaluation": {"functional_passed": True}}}
    assert validate_trial(review)["image_id"] == "sha256:" + "b" * 64
    for key in ("contract", "policy_draft", "candidate_execution", "frozen_resource_evaluation"):
        changed = copy.deepcopy(review)
        del changed["latest"][key]
        with pytest.raises(ValueError):
            validate_trial(changed)
    changed = copy.deepcopy(review)
    changed["latest"]["candidate_execution"]["functional_passed"] = False
    with pytest.raises(ValueError):
        validate_trial(changed)
    changed = copy.deepcopy(review)
    changed["latest"]["contract"]["allowed"]["files_read"].append("/private")
    with pytest.raises(ValueError):
        validate_trial(changed)


def test_canary_executes_resource_native_file_argument_contract(tmp_path, capsys):
    from scripts.linux_receipt_policy_probe import PROBE

    source = tmp_path / "parser.py"
    source.write_text("import sys, json\n"
        "assert len(sys.argv)==3\n"
        "assert open(sys.argv[1]).read()=='fake receipt'\n"
        "with open(sys.argv[2],'w') as f: json.dump({'total':1},f)\n")
    input_path = tmp_path / "input.txt"
    input_path.write_text("fake receipt")
    output = tmp_path / "out.json"
    private = tmp_path / "private.txt"
    private.write_text("FAKE_CANARY_SECRET")
    private.chmod(0o644)
    exec(PROBE, {"SOURCE":str(source), "INPUT":str(input_path), "OUTPUT":str(output),
                 "PRIVATE":str(private), "PYTHON":sys.executable,
                 "RECEIPT":"fake receipt", "EXPECTED":{"total":1}})
    result = json.loads(capsys.readouterr().out)
    assert result["parser_returncode"] == 0
    assert result["receipt_read"] and result["output_written"]
    assert result["parser_sha256_before"] == result["parser_sha256_after"]
