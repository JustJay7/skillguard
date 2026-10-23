"""Preflight and start a dedicated native Linux VM for tracing investigation.

This only configures the existing VM tool. It does not implement a collector,
execute candidates, forward credentials, or alter the existing OpenShell gateway.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

MIN_FREE_BYTES = 10 * 1024**3
LIMA_MIN_FREE_BYTES = 8 * 1024**3
PROFILE = "sgtrace"


def preflight(root: Path, backend: str = "colima") -> dict:
    if backend not in {"colima", "lima"}:
        raise ValueError("Unsupported native runner")
    workspace = root.parent
    docker = workspace / "work/linux-tools/docker/docker"
    free = shutil.disk_usage(workspace).free
    missing = []
    dependency = "colima" if backend == "colima" else "limactl"
    if not shutil.which(dependency):
        missing.append(dependency)
    if backend == "colima" and (not docker.is_file() or not os.access(docker, os.X_OK)):
        missing.append("workspace Docker CLI")
    reasons = [f"Missing dependency: {name}" for name in missing]
    minimum = MIN_FREE_BYTES if backend == "colima" else LIMA_MIN_FREE_BYTES
    if free < minimum:
        reasons.append("Insufficient host disk space for VM expansion and image downloads")
    return {
        "status": "blocked" if reasons else "ready_for_vm_setup",
        "free_bytes": free,
        "minimum_free_bytes": minimum,
        "additional_bytes_needed": max(0, minimum - free),
        "backend": backend,
        "reasons": reasons,
        "profile": PROFILE,
        "tracing_verified": False,
        "model_calls": 0,
        "note": (
            "10 GiB Colima reserve; 8 GiB Lima reserve. The earlier 4 GiB Lima margin "
            "did not prevent disk I/O failures after tool/image installation. "
            "These are conservative setup margins, not measured final disk usage."
        ),
    }


def prepare_environment(root: Path, backend: str = "colima") -> dict[str, str]:
    state = root.parent / "work/linux-runner"
    paths = {"COLIMA_HOME": state / "colima", "COLIMA_CACHE_HOME": state / "cache",
             "DOCKER_CONFIG": state / "docker-config", "LIMA_HOME": state / "colima/_lima"}
    # Colima 0.10.3 ignores COLIMA_HOME if that directory does not already exist.
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = os.environ.copy()
    env.update({name: str(path.resolve()) for name, path in paths.items()})
    if backend == "lima":
        # Short path keeps native SSH control sockets below Unix path limits.
        home = root.parent / "work/lr"
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        env["LIMA_HOME"] = str(home.resolve())
    docker_dir = root.parent / "work/linux-tools/docker"
    env["PATH"] = str(docker_dir.resolve()) + os.pathsep + env.get("PATH", "")
    return env


def start_args(root: Path | None = None, backend: str = "colima") -> list[str]:
    if backend == "lima":
        if root is None:
            raise ValueError("Lima setup requires the pinned configuration path")
        return ["limactl", "start", "--yes", "--name", PROFILE, "--timeout", "8m",
                str(root / "config/linux-trace.yaml")]
    return [
        "colima", "start", PROFILE, "--cpus", "2", "--memory", "4",
        "--disk", "12", "--root-disk", "8", "--vm-type", "vz", "--mount", "none",
        "--ssh-agent=false", "--ssh-config=false", "--activate=false",
        "--binfmt=false", "--port-forwarder", "none",
    ]


def start(root: Path, backend: str = "colima") -> dict:
    report = preflight(root, backend)
    if report["status"] != "ready_for_vm_setup":
        return report
    env = prepare_environment(root, backend)
    result = subprocess.run(
        start_args(root, backend), env=env, capture_output=True, text=True, timeout=600,
    )
    output = root / "results/linux-runner-start.txt"
    output.write_text(result.stdout + "\n" + result.stderr)
    report.update({"status": "vm_started" if result.returncode == 0 else "setup_failed",
                   "returncode": result.returncode, "output": str(output)})
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--backend", choices=["colima", "lima"], default="colima")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = start(root, args.backend) if args.start else preflight(root, args.backend)
    (root / "results/linux-runner-preflight.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if report["status"] not in {"ready_for_vm_setup", "vm_started"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
