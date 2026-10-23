import json
import subprocess
import sys
from pathlib import Path


def test_cli_diff_outputs_json(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(
        json.dumps(
            {
                "files_read": ["/tmp/invoice.txt"],
                "files_written": [],
                "network_hosts": [],
                "processes": ["python3"],
                "tools": [],
            }
        )
    )
    after.write_text(
        json.dumps(
            {
                "files_read": ["/tmp/invoice.txt", "/tmp/private.txt"],
                "files_written": [],
                "network_hosts": ["127.0.0.1:8765"],
                "processes": ["python3", "curl"],
                "tools": [],
            }
        )
    )

    result = subprocess.run(
        [sys.executable, "-m", "skillguard.cli", "diff", str(before), str(after)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["added"]["files_read"] == ["/tmp/private.txt"]
    assert payload["added"]["network_hosts"] == ["127.0.0.1:8765"]


def test_cli_capture_and_decision_persist_across_processes(tmp_path: Path) -> None:
    source = tmp_path / "pending.json"
    source.write_text(
        json.dumps(
            {
                "id": "abcdef12",
                "subsystem": "skills",
                "action": "create",
                "payload": {"action": "create", "name": "receipts", "content": "# Receipt skill"},
            }
        )
    )
    store = tmp_path / "review-store"
    captured = subprocess.run(
        [sys.executable, "-m", "skillguard.cli", "capture", str(source), "--store", str(store)],
        check=True,
        capture_output=True,
        text=True,
    )
    review_id = json.loads(captured.stdout)["review_id"]
    decided = subprocess.run(
        [sys.executable, "-m", "skillguard.cli", "decide", review_id, "--store", str(store)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(decided.stdout)["activation_permitted"] is False
    assert source.exists()
