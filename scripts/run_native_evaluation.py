"""Invoke the installed native Harbor oracle in the dedicated Linux VM.

Only the hash-bound known fictional task is uploaded. No host mounts, provider
environment, agent login or model inference. Harbor owns execution and cleanup.
This Docker BYOT probe is not the OpenShell enforcement/evidence proof.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

from skillguard.review.snapshot import artifact_tree_digest, digest
from skillguard.review.store import ReviewStore

PREFIX = ["limactl", "shell", "--workdir", "/tmp", "sgtrace-clean", "--", "sudo",
          "env", "-i", "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
          "HOME=/root"]
GUEST = """import json, pathlib, subprocess, sys, tarfile
root = pathlib.Path(sys.argv[1]); root.mkdir(mode=0o700)
with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as archive:
    archive.extractall(root, filter='data')
task = root / 'task'
command = ['/opt/skillguard-harbor/bin/harbor', 'run', '-p', str(task),
           '-o', str(root / 'jobs'), '--job-name', 'frozen-parser', '-a', 'oracle',
           '--env', 'docker', '-n', '1', '-k', '1', '-r', '0', '--delete', '--quiet',
           '--artifact', '/workspace/out', '--artifact', '/opt/candidate/parse_receipt.py',
           '--artifact', '/opt/inputs']
with (root / 'harbor-output.txt').open('w') as log:
    run = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=300)
(root / 'command.json').write_text(json.dumps({'command': command, 'returncode': run.returncode}))
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    if (root / 'jobs').exists():
        archive.add(root / 'jobs', arcname='jobs')
    archive.add(root / 'harbor-output.txt', arcname='harbor-output.txt')
    archive.add(root / 'command.json', arcname='command.json')
"""


def run(root: Path, preparation: Path) -> dict:
    report = json.loads(preparation.read_text())
    task = Path(report["task"])
    if artifact_tree_digest(task) != report["task_sha256"]:
        raise ValueError("Prepared native task bytes changed")
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as bundle:
        bundle.add(task, arcname="task")
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env["LIMA_HOME"] = str(root.parent / "work/lr")
    guest_root = "/root/skillguard-" + report["run_id"]
    command = PREFIX + ["python3", "-c", GUEST, guest_root]
    result = subprocess.run(command, input=archive.getvalue(), capture_output=True,
                            timeout=420, env=env, check=False)
    run_dir = preparation.parent
    (run_dir / "transport-stderr.txt").write_bytes(result.stderr)
    (run_dir / "native-job.tar").write_bytes(result.stdout)
    if result.returncode:
        raise RuntimeError("Native Harbor transport failed; retained guest run requires inspection")
    native = run_dir / "native-job"
    native.mkdir(mode=0o700)
    total = 0
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as bundle:
        for member in bundle:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe native job archive")
            if member.isdir():
                continue
            total += member.size
            if total > 30 * 1024**2:
                raise ValueError("Native job artifacts exceed bounded size")
            source = bundle.extractfile(member)
            assert source is not None
            target = native / path
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_bytes(source.read())
            target.chmod(0o600)
    trial_results = [p for p in (native / "jobs").rglob("result.json")
                     if p.parent.name != "frozen-parser"]
    if len(trial_results) != 1:
        raise RuntimeError("Expected exactly one native frozen-resource trial")
    trial = json.loads(trial_results[0].read_text())
    rewards = list((native / "jobs").rglob("custom_reward.json"))
    if len(rewards) != 1 or trial.get("exception_info") is not None:
        raise RuntimeError("Native trial did not complete verification")
    reward = json.loads(rewards[0].read_text())
    from skillguard.evaluation.receipt_grader import grade_outputs

    trial_root = trial_results[0].parent
    parser = trial_root / "artifacts/parse_receipt.py"
    if digest(parser.read_bytes()) != report["parser_sha256"]:
        raise RuntimeError("Native executed parser artifact differs from the reviewed resource")
    expected = json.loads((task / "tests/expectations.json").read_text())
    frozen_artifacts = {}
    if "contract_manifest_sha256" in report:
        from skillguard.evaluation.receipt_contract import load_frozen

        manifest = Path(report["contract_manifest"])
        if digest(manifest.read_bytes()) != report["contract_manifest_sha256"]:
            raise ValueError("Frozen contract manifest changed during native evaluation")
        development, heldout = load_frozen(manifest)
        cases = development if report["contract_split"] == "development" else heldout
        inputs = {name: (trial_root / "artifacts/inputs" / f"{name}.txt").read_text()
                  for name in cases}
        if (inputs != {name: case["input"] for name, case in cases.items()}
                or expected != {name: case["expected"] for name, case in cases.items()}):
            raise ValueError("Native input/output contract differs from the frozen suite")
        frozen_artifacts = {"contract.json": manifest.read_bytes(),
                            "suite.json": (manifest.parent / (report["contract_split"] + ".json"))
                                .read_bytes(),
                            "inputs.json": json.dumps(inputs, sort_keys=True).encode()}
    recomputed = grade_outputs(trial_root / "artifacts/out", expected)
    if reward != recomputed:
        raise RuntimeError("Native grader reward differs from collected output checks")
    if artifact_tree_digest(task) != report["task_sha256"]:
        raise RuntimeError("Prepared task changed during native execution")
    output = {**report, "execution": "completed_frozen_resource_probe",
              "functional_passed": reward["overall"] == 1.0,
              "reward": reward, "native_trial_result": str(trial_results[0]),
              "native_job_artifacts_sha256": artifact_tree_digest(native),
              "native_job_archive_sha256": digest(result.stdout),
              "limitations": ["Frozen parser oracle, no live agent or Skill Lift",
                               "Authored fictional checks, no generated attack coverage",
                               "Native Docker BYOT, no OpenShell policy proof or Sysdig capture",
                               "Partial runtime evidence; activation unavailable"],
              "command": command[:-3] + ["<operator-owned guest invocation>"]}
    (run_dir / "execution.json").write_text(json.dumps(output, indent=2) + "\n")
    artifacts = frozen_artifacts | {
        "trial.json": trial_results[0].read_bytes(), "reward.json": rewards[0].read_bytes(),
        "parser.py": parser.read_bytes(),
        "expectations.json": (task / "tests/expectations.json").read_bytes(),
        "outputs.json": json.dumps({
            name: (trial_root / "artifacts/out" / f"{name}.json").read_text()
            for name in expected
        }, sort_keys=True).encode(),
    }
    store = ReviewStore(Path(report["store"]))
    store.record_frozen_resource_evaluation(report["review_id"], report=json.dumps({
        "scope": "bounded_native_harbor_oracle", "complete": False,
        "activation_eligible": False, "skill_lift": None,
        "candidate_sha256": report["candidate_sha256"],
        **({"contract_split": report["contract_split"],
            "contract_manifest_sha256": report["contract_manifest_sha256"]}
           if frozen_artifacts else {}),
        "artifacts": {key: digest(value) for key, value in artifacts.items()},
    }).encode(), artifacts=artifacts)
    decision = store.decide(report["review_id"])
    output["decision"] = decision
    (run_dir / "candidate-review-final.json").write_text(json.dumps(decision, indent=2) + "\n")
    (run_dir / "execution.json").write_text(json.dumps(output, indent=2) + "\n")
    (root / "results/native-evaluation-latest.json").write_text(json.dumps(output, indent=2) + "\n")
    return output


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    latest = json.loads((root / "results/native-evaluation-latest.json").read_text())
    preparation = root / "results/integration" / latest["run_id"] / "preparation.json"
    env = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
    env["LIMA_HOME"] = str(root.parent / "work/lr")
    run_dir = preparation.parent
    try:
        start = subprocess.run(["limactl", "start", "--yes", "sgtrace-clean"], env=env,
                               capture_output=True, text=True, timeout=180, check=False)
        (run_dir / "vm-start.txt").write_text(start.stdout + start.stderr)
        if start.returncode:
            raise RuntimeError("Dedicated native evaluation runner failed to start")
        output = run(root, preparation)
    finally:
        stop = subprocess.run(["limactl", "stop", "--yes", "sgtrace-clean"], env=env,
                              capture_output=True, text=True, timeout=120, check=False)
        (run_dir / "vm-stop.txt").write_text(stop.stdout + stop.stderr)
        if stop.returncode:
            raise RuntimeError("Native evaluation VM cleanup failed")
    print(json.dumps({key: output[key] for key in (
        "run_id", "execution", "functional_passed", "reward", "activation_eligible"
    )}, indent=2))


if __name__ == "__main__":
    main()
