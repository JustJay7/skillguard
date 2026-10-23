import json

import pytest

from scripts.receipt_workflow import workflow
from skillguard.review.snapshot import digest
from tests.test_candidate_image import setup
from tests.test_receipt_repair_contract import fixture


@pytest.mark.parametrize("change", ["source", "manifest", "suite"])
def test_changed_workflow_inputs_are_refused_before_starting_runner(tmp_path, monkeypatch, change):
    preparation, candidate = setup(tmp_path, monkeypatch)
    manifest = fixture(tmp_path)
    data = json.loads(preparation.read_text()) | {
        "frozen_contract_manifest": str(manifest),
        "frozen_contract_manifest_sha256": digest(manifest.read_bytes())}
    preparation.write_text(json.dumps(data))
    monkeypatch.setattr("scripts.receipt_workflow.subprocess.run",
                        lambda *a, **kw: pytest.fail("No runner or model should start"))
    if change == "source":
        (candidate / "scripts/parse_receipt.py").write_text("changed")
    elif change == "manifest":
        manifest.chmod(0o600)
        raw = json.loads(manifest.read_text()) | {"frozen_at": "changed"}
        manifest.write_text(json.dumps(raw))
    else:
        path = manifest.parent / "heldout.json"
        path.chmod(0o600)
        path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError):
        workflow(tmp_path, preparation)


def test_oversized_native_workload_name_is_refused_before_guest_commands(monkeypatch, capsys):
    from scripts import linux_kernel_probe

    monkeypatch.setattr("sys.argv", ["probe", "--sandbox", "sg-linux-trace-r1234"])
    monkeypatch.setattr(linux_kernel_probe.subprocess, "run",
                        lambda *a, **kw: pytest.fail("Invalid name must not start native work"))
    with pytest.raises(SystemExit) as result:
        linux_kernel_probe.main()
    assert result.value.code == 2
    assert "19-character" in capsys.readouterr().err


def test_native_command_timeout_is_saved_for_cleanup_and_review(tmp_path, monkeypatch):
    import subprocess

    from scripts.receipt_workflow import recorded_command

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 5, output=b"partial native output\n")

    monkeypatch.setattr(subprocess, "run", timeout)
    result = recorded_command(["native-tool"], root=tmp_path, env={},
                              output=tmp_path / "timeout.txt", timeout=5)
    assert result.returncode == 124
    assert "partial native output" in (tmp_path / "timeout.txt").read_text()
    assert "timed out after 5 seconds" in result.stderr


def test_receipt_workflow_records_native_file_policy_without_process_allowlist(tmp_path):
    from scripts.receipt_workflow import record_file_policy
    from tests.test_frozen_resource_review import fixture as review_fixture

    store, rid, _, _ = review_fixture(tmp_path)
    event = record_file_policy(store, rid)
    policy = event["data"]["policy"]
    assert policy["filesystem_policy"]["read_write"] == [
        "/dev/null", "/sandbox/receipt-output.json"]
    assert policy["landlock"]["compatibility"] == "hard_requirement"
    assert event["data"]["applied"] is False
    assert store.decide(rid)["activation_permitted"] is False
