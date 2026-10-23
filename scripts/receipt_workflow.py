"""Compose native staged repair, frozen evaluation, Sysdig review and policy draft.

No replacement harness or activation bypass. Existing native tools execute;
this orchestration records the evidence and leaves incomplete reviews pending.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import uuid
from pathlib import Path

from scripts.learned_candidate_image import candidate_payload
from scripts.linux_runner import prepare_environment
from scripts.prepare_native_evaluation import prepare
from scripts.run_native_evaluation import PREFIX, run
from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.evaluation.receipt_contract import load_frozen
from skillguard.review.snapshot import digest
from skillguard.review.store import ReviewStore


def recorded_command(args: list[str], *, root: Path, env: dict[str, str],
                     output: Path, timeout: int) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, cwd=root, env=env, capture_output=True,
                                text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        result = subprocess.CompletedProcess(
            args, 124, decoded(error.stdout),
            decoded(error.stderr) + f"\nNative command timed out after {timeout} seconds\n")
    output.write_text(result.stdout + result.stderr)
    return result


def record_file_policy(store: ReviewStore, review_id: str) -> dict:
    # Native filesystem rules cannot encode process/tool allowlists. Keep that
    # limitation explicit instead of giving the policy compiler unsupported claims.
    store.record_contract(review_id, BehavioralEnvelope(
        files_read={"/opt/skillguard-candidate/scripts/parse_receipt.py",
                    "/opt/skillguard-fixtures/input.txt"},
        files_written={"/sandbox/receipt-output.json"}))
    return store.record_policy_draft(
        review_id, runtime_read_only=["/bin", "/usr", "/lib", "/etc", "/proc", "/dev/urandom"])


def workflow(root: Path, preparation: Path, *, explain: bool = False) -> dict:
    parent = json.loads(preparation.read_text())
    candidate_payload(root, preparation)
    manifest = Path(parent["frozen_contract_manifest"])
    load_frozen(manifest)
    if digest(manifest.read_bytes()) != parent["frozen_contract_manifest_sha256"]:
        raise ValueError("Repair and frozen contract identities differ")
    folder = root / "results/integration" / f"receipt-workflow-{uuid.uuid4().hex[:8]}"
    folder.mkdir(mode=0o700)
    env = prepare_environment(root, "lima")
    store = ReviewStore(Path(parent["store"]))
    report = {
        "run_id": folder.name,
        "candidate_sha256": parent["candidate_sha256"],
        "preparation": str(preparation),
        "contract_manifest": str(manifest),
        "contract_manifest_sha256": digest(manifest.read_bytes()),
        "evaluations": [],
        "complete": False,
        "activation_permitted": False,
        "scope": "Native frozen parser workflow; not live agent or Skill Lift",
    }

    def command(args: list[str], name: str, timeout: int = 180) -> subprocess.CompletedProcess:
        return recorded_command(args, root=root, env=env, output=folder / name, timeout=timeout)

    try:
        if command(["limactl", "start", "--yes", "--timeout", "90s", "sgtrace-clean"],
                   "vm-start.txt", timeout=120).returncode:
            raise RuntimeError("Native runner did not start")
        # Both versions use the exact same frozen authored inputs and domain oracle.
        # New development must pass before any unseen test is released.
        original = root / "results/integration/local-parser-0a9ae65b/preparation.json"
        for label, source, split in (
            ("repair", preparation, "development"),
            ("repair", preparation, "heldout"),
            ("original", original, "development"),
            ("original", original, "heldout"),
        ):
            task = prepare(root, source, contract_manifest=manifest, split=split)
            result = run(root, root / "results/integration" / task["run_id"] / "preparation.json")
            report["evaluations"].append(
                {
                    "version": label,
                    "split": split,
                    "run_id": result["run_id"],
                    "candidate_sha256": result["candidate_sha256"],
                    "passed": result["functional_passed"],
                    "cases": result["reward"]["details"],
                }
            )
            if label == "repair" and split == "development" and not result["functional_passed"]:
                raise RuntimeError("Repair failed development; unseen suite remains sealed")
        status = command(PREFIX + ["openshell", "status"], "gateway-status.txt")
        if status.returncode or "Status: Connected" not in status.stdout:
            gateway = command(
                PREFIX
                + [
                    "systemd-run",
                    "--unit=skillguard-openshell",
                    "--uid=root",
                    "--property=SetLoginEnvironment=yes",
                    "--property=UMask=0077",
                    "--setenv=OPENSHELL_LOCAL_TLS_DIR=/root/.local/state/openshell/tls",
                    "/usr/bin/openshell-gateway",
                ],
                "gateway-start.txt",
            )
            if gateway.returncode:
                raise RuntimeError("Existing native gateway could not start")
        probe = command(
            [
                str(root / ".venv/bin/python"),
                "-m",
                "scripts.linux_kernel_probe",
                "--sandbox",
                "sg-linux-trace-r" + uuid.uuid4().hex[:3],
                "--capture-startup",
                "--prepared-parser",
                str(preparation),
                "--compare-control",
            ],
            "kernel-probe.txt",
        )
        report["native_capture"] = json.loads(
            (root / "results/kernel-backend-latest.json").read_text()
        )
        if probe.returncode:
            raise RuntimeError("Native capture probe failed; evidence retained")
        regions = command([str(root / '.venv/bin/python'), '-m',
            'scripts.analyze_native_mapping_regions', '--folder',
            str(root / 'results/integration' / report['native_capture']['run_id'])],
            'mapping-region-analysis.txt')
        if regions.returncode:
            raise RuntimeError('Native mapping-region analysis failed; evidence retained')
        report['mapping_regions'] = json.loads(
            (root / 'results/mapping-regions-latest.json').read_text())
        capture_folder = root / 'results/integration' / report['native_capture']['run_id']
        directory_controls = command([str(root / '.venv/bin/python'), '-m',
            'scripts.analyze_native_directory_controls', '--folder', str(capture_folder)],
            'directory-control-analysis.txt')
        if directory_controls.returncode:
            raise RuntimeError('Native directory/TMPFILE control verification failed')
        report['directory_controls'] = json.loads(
            (capture_folder / 'directory-controls.json').read_text())
        socket_controls = command([str(root / '.venv/bin/python'), '-m',
            'scripts.analyze_native_socket_controls', '--folder', str(capture_folder)],
            'socket-control-analysis.txt')
        if socket_controls.returncode:
            raise RuntimeError('Native socket/IPC control verification failed')
        report['socket_controls'] = json.loads(
            (capture_folder / 'socket-controls.json').read_text())
        file_identity_controls = command([str(root / '.venv/bin/python'), '-m',
            'scripts.analyze_native_file_identity', '--folder', str(capture_folder)],
            'file-identity-control-analysis.txt')
        if file_identity_controls.returncode:
            raise RuntimeError('Native file identity control verification failed')
        report['file_identity_controls'] = json.loads(
            (capture_folder / 'file-identity-controls.json').read_text())
        draft = record_file_policy(store, parent["review_id"])
        report["policy_draft"] = draft["data"]
        enforcement = command(
            [str(root / ".venv/bin/python"), "-m", "scripts.linux_receipt_policy_probe",
             "--preparation", str(preparation)], "file-policy-trial.txt", timeout=480)
        if enforcement.returncode:
            raise RuntimeError("Native file-policy trial failed; candidate remains pending")
        proof = json.loads((root / "results/receipt-policy-latest.json").read_text())
        if proof["candidate_sha256"] != parent["candidate_sha256"]:
            raise ValueError("Native file-policy trial belongs to another candidate")
        report["file_enforcement"] = proof["file_enforcement"]
        report["file_policy_run_id"] = proof["run_id"]
        metadata = command(
            [str(root / ".venv/bin/python"), "-m", "scripts.linux_receipt_policy_probe",
             "--preparation", str(preparation), "--metadata-diagnostic"],
            "metadata-policy-trial.txt", timeout=480)
        if metadata.returncode:
            raise RuntimeError("Native metadata diagnostic failed; candidate remains pending")
        diagnostic = json.loads((root / "results/metadata-policy-latest.json").read_text())
        if diagnostic["candidate_sha256"] != parent["candidate_sha256"]:
            raise ValueError("Native metadata diagnostic belongs to another review")
        report["metadata_policy_probe"] = diagnostic["metadata_policy_probe"]
        report["metadata_policy_run_id"] = diagnostic["run_id"]
        if explain:
            advice = command(
                [
                    str(root / ".venv/bin/python"),
                    "-m",
                    "scripts.explain_receipt_demo",
                    "--store",
                    parent["store"],
                    "--review",
                    parent["review_id"],
                    "--budget-cap",
                    "0.75",
                ],
                "model-advice.txt",
            )
            if advice.returncode:
                raise RuntimeError("Metadata-only advice failed; deterministic review retained")
        report["decision"] = store.decide(parent["review_id"])
        report["frozen_contract_passed"] = store.evidence(parent["review_id"])["E10"]["value"][
            "functional_passed"
        ]
    except Exception as error:
        report["error"] = str(error)
        report["decision"] = store.decide(parent["review_id"])
    finally:
        stop = command(["limactl", "stop", "sgtrace-clean"], "vm-stop.txt", timeout=60)
        if stop.returncode:
            command(["limactl", "stop", "--force", "sgtrace-clean"],
                    "vm-force-stop.txt", timeout=30)
        states = command(["limactl", "list", "--json"], "runner-states.json", timeout=30)
        report["runner_states"] = {
            v["name"]: v["status"] for v in map(json.loads, states.stdout.splitlines())
        }
        report["runner_stopped"] = (states.returncode == 0
            and report["runner_states"].get("sgtrace-clean") == "Stopped")
        profile = preparation.parent / "staging-profile"
        pending = profile / "pending/skills" / f"{parent['native_pending_id']}.json"
        review = store.get(parent["review_id"])
        report["pending_preserved"] = (
            pending.is_file() and digest(pending.read_bytes()) == review["pending_sha256"]
        )
        report["active_skill_absent"] = not (profile / "skills/receipt-organizer").exists()
        try:
            report["candidate_unchanged"] = bool(candidate_payload(root, preparation))
        except ValueError as error:
            report["candidate_unchanged"] = False
            report["error"] = str(error)
        value = store.evidence(parent["review_id"]).get("E10", {}).get("value", {})
        report["frozen_contract_passed"] = value.get("functional_passed", False)
        output = json.dumps(report, indent=2) + "\n"
        (folder / "workflow.json").write_text(output)
        (root / "results/receipt-workflow-latest.json").write_text(output)
    return report


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--preparation", type=Path)
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args()
    source = args.preparation
    if source is None:
        latest = json.loads((root / "results/local-parser-latest.json").read_text())
        source = root / "results/integration" / latest["run_id"] / "preparation.json"
    report = workflow(root, source, explain=args.explain)
    print(
        json.dumps(
            {
                key: report.get(key)
                for key in (
                    "run_id",
                    "evaluations",
                    "frozen_contract_passed",
                    "decision",
                    "error",
                    "runner_stopped",
                    "pending_preserved",
                    "active_skill_absent",
                    "candidate_unchanged",
                )
            },
            indent=2,
        )
    )
    if report.get("error") or not report["runner_stopped"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
