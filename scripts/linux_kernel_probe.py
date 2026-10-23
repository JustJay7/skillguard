"""Repeat a fixed fake-data experiment with existing OpenShell/Sysdig/strace.

Requires the dedicated Linux VM; startup mode creates a fresh native workload.
Optionally executes only the archived known parser with an empty Python control.
No model requests, evaluation dataset, monitoring service or activation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import uuid
from pathlib import Path

from scripts.learned_candidate_image import EXPECTED, candidate_payload, guest_image_source
from scripts.linux_runner import prepare_environment
from skillguard.traces.file_identity import analyze_file_identity
from skillguard.traces.process_scope import PROCESS_FORMAT, compare_parser_to_control
from skillguard.traces.sysdig import (
    SYSDIG_FORMAT,
    capture_failures,
    parse_sysdig,
    parse_sysdig_stats,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vm", default="sgtrace-clean")
    parser.add_argument("--sandbox", required=True)
    parser.add_argument("--simulate-collector-loss", action="store_true",
                        help="Kill only this fixed probe's native collector after readiness")
    parser.add_argument("--capture-startup", action="store_true",
                        help="Start native capture before creating a fresh fixed workload")
    parser.add_argument("--prepared-parser", type=Path,
                        help="Archived successful preparation of the one known learned guide")
    parser.add_argument("--compare-control", action="store_true",
                        help="Compare this known parser's native process tree to empty Python")
    args = parser.parse_args()
    if args.prepared_parser and (not args.capture_startup or args.simulate_collector_loss):
        parser.error("Known candidate execution requires startup capture without a fault injection")
    if args.compare_control and not args.prepared_parser:
        parser.error("Process comparison requires the known prepared parser")
    if not re.fullmatch(r"sgtrace(?:-[a-z0-9-]+)?", args.vm):
        parser.error("Only dedicated Linux test VMs are accepted")
    if not re.fullmatch(r"sg-linux-trace-[a-z0-9-]+", args.sandbox) or len(args.sandbox) > 19:
        parser.error("Fixed-probe workload names must meet the native 19-character limit")
    root = Path(__file__).resolve().parents[1]
    suffix = uuid.uuid4().hex[:8]
    run = root / "results/integration" / f"kernel-{suffix}"
    run.mkdir(mode=0o700)
    env = prepare_environment(root, "lima")
    guest = f"/root/kernel-evidence-{suffix}"
    unit = f"skillguard-sysdig-{suffix}"
    binary = "/opt/skillguard-sysdig/usr/bin/sysdig"
    plugins = "/opt/skillguard-sysdig/usr/share/sysdig/plugins"
    event_format = PROCESS_FORMAT if args.compare_control else SYSDIG_FORMAT
    prefix = ["limactl", "shell", "--workdir", "/tmp", args.vm, "--", "sudo"]
    started = time.monotonic()
    report = {"run_id": run.name, "vm": args.vm, "sandbox": args.sandbox,
              "model_calls": 0, "complete": False, "activation_eligible": False,
              "scope": "fixed_fake_data_probe",
              "simulated_collector_loss": args.simulate_collector_loss,
              "capture_startup": args.capture_startup}
    if args.prepared_parser:
        report["scope"] = "known_learned_candidate_probe"

    def native(command: list[str], *, data: str | None = None, check: bool = True) -> str:
        outcome = subprocess.run(prefix + command, input=data, capture_output=True,
                                 text=True, env=env, timeout=90)
        if check and outcome.returncode:
            raise RuntimeError(f"Native test command failed: {command[:3]}: {outcome.stderr[:300]}")
        return outcome.stdout

    collector_started = False
    try:
        native(["install", "-m", "700", "-d", guest])
        prepared, image = None, None
        if args.prepared_parser:
            prepared = candidate_payload(root, args.prepared_parser)
            image = json.loads(native(["python3", "-"], data=guest_image_source(
                prepared, compare_control=args.compare_control)))
            (run / "candidate-image.json").write_text(json.dumps(image, indent=2))
            (run / "prepared-candidate.json").write_text(json.dumps(prepared, indent=2))
        version = native(["env", f"SYSDIG_PLUGIN_DIR={plugins}", binary, "--version"])
        if version.strip() != "sysdig version 0.41.4":
            raise RuntimeError("Unexpected native Sysdig version")
        report["sysdig_version"] = version.strip()
        ids = native(["docker", "ps", "-q", "--filter",
                      "label=openshell.ai/isolation-role=sandbox"]).split()
        containers = [json.loads(native(["docker", "inspect", value]))[0] for value in ids]
        target = [value for value in containers if value["Name"].startswith(
            f"/openshell-default--{args.sandbox}-")]
        if args.capture_startup and target:
            raise RuntimeError("Startup capture requires an absent fresh workload")
        if not args.capture_startup and len(target) != 1:
            raise RuntimeError("Ambiguous native workload identity before capture")
        initial_container = target[0]["Id"] if target else None
        ready_marker = guest + "/native-ready.txt"
        capture_file = guest + "/events.scap"
        capture_filter = [] if args.capture_startup else [
            "-d", "container.id=" + initial_container[:12]]
        output_flags = ["-w", capture_file] if args.capture_startup else [
            "-j", "-p", event_format, *capture_filter]
        native(["systemd-run", f"--unit={unit}", "--uid=root", "--property=UMask=0077",
                "--property=RuntimeMaxSec=120", f"--setenv=SYSDIG_PLUGIN_DIR={plugins}",
                f"--property=StandardOutput=append:{guest}/events.jsonl",
                f"--property=StandardError=append:{guest}/stats.txt",
                binary, "--modern-bpf", "-s", "1", "-E", "-v", *output_flags])
        collector_started = True
        report["collector_pid"] = int(native(
            ["systemctl", "show", unit, "--value", "-p", "MainPID"]).strip())
        if report["collector_pid"] <= 0:
            raise RuntimeError("Native collector not running")
        # One-time native-output readiness barrier, before any fixed probe runs.
        # An active service PID alone previously missed the entire short probe.
        readiness = '''
import json, time
from pathlib import Path
path = Path(EVENTS_PATH)
deadline = time.monotonic() + 15
position, pending = 0, ''
while time.monotonic() < deadline:
    if path.exists():
        with path.open() as stream:
            stream.seek(position)
            pending += stream.read()
            position = stream.tell()
        lines = pending.split('\\n')
        pending = lines.pop()
        for line in lines:
            if not line:
                continue
            row = json.loads(line)
            if ((CONTAINER_ID and row.get('container.full_id') == CONTAINER_ID)
                or (not CONTAINER_ID and row.get('fd.name') == READY_PATH
                    and row.get('evt.type') == 'write' and row.get('evt.dir') == '<'
                    and row.get('evt.rawres') == 5)):
                print(json.dumps({'event': row['evt.num'], 'time': row['evt.rawtime']}))
                raise SystemExit(0)
    time.sleep(0.05)
raise SystemExit('Native capture readiness not established')
'''.replace("EVENTS_PATH", repr(guest + "/events.jsonl")).replace(
            "CONTAINER_ID", repr(initial_container)).replace("READY_PATH", repr(ready_marker))
        if args.capture_startup:
            # Parse a live prefix with native Sysdig; only an actual marker event
            # establishes readiness. A partial-file reader error is not success.
            readiness = """
import json, subprocess, time
from pathlib import Path
deadline = time.monotonic() + 15
while time.monotonic() < deadline:
    Path(READY_PATH).write_bytes(b'READY')
    outcome = subprocess.run(READER, capture_output=True, text=True, timeout=5)
    for line in outcome.stdout.splitlines():
        row = json.loads(line)
        if (row.get('fd.name') == READY_PATH and row.get('evt.type') == 'write'
            and row.get('evt.dir') == '<' and row.get('evt.rawres') == 5):
            print(json.dumps({'event': row['evt.num'], 'time': row['evt.rawtime']}))
            raise SystemExit(0)
    time.sleep(.05)
raise SystemExit('Native capture-file readiness not established')
""".replace("READY_PATH", repr(ready_marker)).replace("READER", repr([
                "env", f"SYSDIG_PLUGIN_DIR={plugins}", binary,
                "-r", capture_file, "-j", "-p", event_format,
                "-d", "fd.name=" + ready_marker + " and evt.type=write and evt.dir=<",
            ]))
        report["native_readiness"] = json.loads(native(["python3", "-"], data=readiness))
        if args.capture_startup:
            startup = (
                "from pathlib import Path; import os; "
                "Path('/sandbox/startup-marker.txt').write_text('FAKE_STARTUP_MARKER'); "
                "os.execv('/usr/bin/sleep', ['sleep', '3600'])"
            )
            startup_command = ["python", "-c", startup]
            if prepared:
                startup_command = ["python", "/opt/skillguard-launch.py"]
            native(["openshell", "sandbox", "create", "--name", args.sandbox,
                    "--from", image["image"] if prepared else "skillguard-trace:fixed",
                    "--policy", image["policy"] if prepared else "/root/trace-policy.yaml",
                    "--detach", "--no-auto-providers", "--", *startup_command])
            ids = native(["docker", "ps", "-q", "--filter",
                          "label=openshell.ai/isolation-role=sandbox"]).split()
            containers = [json.loads(native(["docker", "inspect", value]))[0] for value in ids]
            target = [value for value in containers if value["Name"].startswith(
                f"/openshell-default--{args.sandbox}-")]
            if len(target) != 1:
                raise RuntimeError("Ambiguous startup workload identity")
            initial_container = target[0]["Id"]
            if prepared:
                if target[0]["Image"] != image["image_id"]:
                    raise RuntimeError("Actual workload image differs from prepared candidate")
                # Native root readback; this file is workload-written, not an attestation.
                deadline = time.monotonic() + 40
                while True:
                    raw_execution = native(["docker", "exec", initial_container,
                        "cat", "/sandbox/candidate-execution.json"], check=False)
                    if raw_execution:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError("Candidate execution outcome not available")
                    time.sleep(.1)
                (run / "candidate-execution.json").write_text(raw_execution)
                execution = json.loads(raw_execution)
                report["candidate_execution"] = {
                    "candidate_sha256": prepared["candidate_sha256"],
                    "parser_sha256": prepared["parser_sha256"],
                    "review_id": prepared["review_id"], "store": prepared["store"],
                    "image_id": image["image_id"],
                    "source_hashes_match": execution.get("candidate_sha256_before")
                        == execution.get("candidate_sha256_after") == prepared["candidate_sha256"],
                    "functional_passed": execution.get("returncode") == 0
                        and execution.get("record") == EXPECTED,
                    "mismatched_fields": [key for key, value in EXPECTED.items()
                        if (execution.get("record") or {}).get(key) != value],
                    "scope": "Known pending derivative; "
                        "workload report corroboration remains partial",
                    "receipt_shared_with_model": False,
                }
        if args.simulate_collector_loss:
            # Operator-controlled infrastructure fault, never candidate code.
            native(["systemctl", "kill", "--signal=SIGKILL", unit])
            deadline = time.monotonic() + 5
            while True:
                state_text = native(["systemctl", "show", unit, "-p", "ActiveState",
                                     "-p", "ExecMainCode", "-p", "ExecMainStatus", "-p", "Result"])
                state = dict(line.split("=", 1) for line in state_text.splitlines() if "=" in line)
                if state.get("ActiveState") not in {"active", "deactivating"}:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Native collector loss not confirmed before fixed task")
                time.sleep(0.05)
            report["collector_loss_state"] = state
            (run / "collector-loss-state.txt").write_text(state_text)
        source = root / "scripts/linux_trace_probe_guest.py"
        raw = native(["python3", "-", args.sandbox], data=source.read_text(), check=False)
        (run / "probe-console.json").write_text(raw)
        probe = json.loads(raw)
        report["collector_active_after_probe"] = native(
            ["systemctl", "show", unit, "--value", "-p", "ActiveState"], check=False
        ).strip() == "active"
        native(["systemctl", "stop", unit], check=False)
        stats_text = native(["cat", guest + "/stats.txt"])
        (run / "capture-stats.txt").write_text(stats_text)
        try:
            stats = parse_sysdig_stats(stats_text)
        except ValueError as error:
            stats = None
            report["stats_error"] = str(error)
        # Preserve failed captures and fixed-task outcome before evaluating them.
        container = json.loads(native(["cat", probe["run"] + "/container.json"]))
        if container["id"] != initial_container:
            raise RuntimeError("Native workload changed during the fixed probe")
        if args.capture_startup:
            with (run / "events.scap").open("wb") as output:
                subprocess.run(prefix + ["cat", capture_file], stdout=output,
                               stderr=subprocess.PIPE, env=env, check=True, timeout=60)
            raw_metadata = native([
                "env", f"SYSDIG_PLUGIN_DIR={plugins}", binary, "-r", capture_file,
                "-j", "-p", event_format, "-d", "container.id=" + initial_container[:12],
            ])
            report["native_capture_mode"] = "capture_file"
        else:
            raw_metadata = native(["cat", guest + "/events.jsonl"])
        (run / "raw-events.jsonl").write_text(raw_metadata)
        # Startup warmup remains archived; only the declared post-readiness window
        # is adapted. No arbitrary candidate code ran before that boundary.
        metadata = "\n".join(line for line in raw_metadata.splitlines()
                             if json.loads(line)["evt.num"] >= report["native_readiness"]["event"])
        (run / "workload.jsonl").write_text(metadata)
        (run / "container.json").write_text(json.dumps(container, indent=2) + "\n")
        for remote, filename in ((probe["run"] + "/trace.txt", "strace.txt"),
                                 (probe["run"] + "/fixed-probe.py", "fixed-probe.py"),
                                 (probe["run"] + "/native-sandbox.json", "native-sandbox.json")):
            with (run / filename).open("wb") as output:
                subprocess.run(prefix + ["cat", remote], stdout=output,
                               stderr=subprocess.PIPE, env=env, check=True, timeout=60)
        report.update({"native_stats": stats, "workload_checks": probe.get("workload_checks", {}),
                       "container_id": container["id"], "image_id": container["image"],
                       "probe_sha256": probe["probe_sha256"],
                       "sandbox_stopped": probe.get("stopped_phase") == "Stopped"})
        evidence = parse_sysdig(metadata, container_id=container["id"])
        if args.compare_control:
            if execution.get("control_returncode") != 0:
                raise RuntimeError("Empty Python control did not exit successfully")
            comparison = compare_parser_to_control(metadata, container_id=container["id"],
                page_size=report['workload_checks']['mapping_lifecycle_checks']['page_size'],
                include_file_identity=True)
            (run / "process-comparison.json").write_text(json.dumps(comparison, indent=2))
            report["process_comparison"] = comparison
        (run / "envelope.json").write_text(json.dumps(evidence.envelope.to_dict(), indent=2))
        (run / "event-references.json").write_text(json.dumps(evidence.event_refs, indent=2))
        (run / 'directory-opens.json').write_text(json.dumps(evidence.directory_opens, indent=2))
        (run / 'socket-io.json').write_text(json.dumps(evidence.socket_io, indent=2))
        (run / 'file-identity.json').write_text(json.dumps(
            analyze_file_identity(metadata, container_id=container['id']), indent=2))
        (run / "memory-mappings.json").write_text(json.dumps({
            "file_mappings": evidence.memory_mappings,
            "mapping_changes": evidence.mapping_changes,
            "anonymous_count": evidence.anonymous_mappings,
            "capabilities": evidence.mapping_capabilities.to_dict(),
            "unresolved_events": evidence.unresolved_events,
            "complete": False, "page_access_observed": False,
        }, indent=2))
        (run / "file-transfers.json").write_text(json.dumps(evidence.file_transfers, indent=2))
        (run / "file-mutations.json").write_text(json.dumps({
            "mutations": evidence.file_mutations,
            "possible_creation_capabilities": evidence.path_mutation_capabilities.to_dict(),
            "complete": False,
        }, indent=2))
        checks = probe.get("workload_checks", {})
        marker = "/sandbox/fixed-trace-probe/untraced-marker.txt"
        events = [json.loads(line) for line in metadata.splitlines()]
        escaped_write = [row for row in events if row["evt.type"] == "write"
                         and row["evt.dir"] == "<" and row.get("fd.name") == marker
                         and row.get("evt.rawres") == 26
                         and row.get("thread.vtid") == checks.get("clone_untraced_pid")]
        startup_write = [row for row in events if row["evt.type"] == "write"
                         and row["evt.dir"] == "<"
                         and row.get("fd.name") == "/sandbox/startup-marker.txt"
                         and row.get("evt.rawres") == 19
                         and row.get("evt.rawtime", 0) >= report["native_readiness"]["time"]
                         and row.get("container.full_id") == initial_container]
        strace = (run / "strace.txt").read_text()
        omitted_by_strace = not any(marker in line and "openat(" in line
                                   and "O_WRONLY" in line for line in strace.splitlines())
        mmap_modes = {
            "/sandbox/fixed-trace-probe/mapped-read.txt": (True, False),
            "/sandbox/fixed-trace-probe/mapped-private.txt": (True, False),
            "/sandbox/fixed-trace-probe/mapped-shared.txt": (True, True),
        }
        mmap_refs = {path: [m for m in evidence.memory_mappings if m["path"] == path
                           and (m["readable"], m["writable"] and m["shared"]) == modes]
                     for path, modes in mmap_modes.items()}
        mmap_coverage = all(mmap_refs.values()) and all(checks.get(key) is True for key in (
            "mmap_read_correct", "mmap_private_changed", "mmap_private_source_unchanged",
            "mmap_shared_source_changed"))
        report["fixed_mapping_probe"] = {
            "passed": mmap_coverage, "native_references": mmap_refs,
            "scope": "Known fake-data probe; permissions mapped, not arbitrary page access proof",
            "complete": False,
        }
        lifecycle = checks.get("mapping_lifecycle_checks", {})
        by_ref = {f"sysdig:{r['evt.num']}": r for r in events}
        changes = [m for m in evidence.mapping_changes
                   if m["address"] == lifecycle.get("address")
                   and m["length"] == str(lifecycle.get("page_size"))
                   and by_ref[m["exit_ref"]].get("thread.vtid") == lifecycle.get("thread_vtid")]
        lifecycle_refs = {kind: [m for m in changes if m["kind"] == kind]
                          for kind in ("mprotect", "munmap")}
        lifecycle_coverage = (all(len(refs) == 1 for refs in lifecycle_refs.values())
            and lifecycle_refs["mprotect"][0]["protection"] == "PROT_READ|PROT_WRITE"
            and lifecycle.get("mprotect_returncode") == 0
            and lifecycle.get("munmap_returncode") == 0
            and lifecycle.get("shared_source_changed") is True
            and lifecycle.get("failed_mprotect_returncode") == -1
            and all(m["exit_ref"] in evidence.unresolved_events for m in changes))
        report["fixed_mapping_lifecycle_probe"] = {
            "passed": lifecycle_coverage, "native_references": lifecycle_refs,
            "scope": "Observed changes retained as gaps; backing ranges not reconstructed",
            "complete": False,
        }
        transfer_source = "/sandbox/fixed-trace-probe/transfer-source.txt"
        transfer_refs = {kind: [t for t in evidence.file_transfers if t["kind"] == kind
                        and t["source_file"] == transfer_source and t["bytes_transferred"] == 16
                        and t["destination_file"] == "/sandbox/fixed-trace-probe/" + kind
                        + "-output.txt"] for kind in ("sendfile", "copy_file_range")}
        splice_read = [t for t in evidence.file_transfers if t["kind"] == "splice"
                       and t["source_file"] == transfer_source and t["bytes_transferred"] == 16]
        splice_write = [t for t in evidence.file_transfers if t["kind"] == "splice"
                        and t["destination_file"] == "/sandbox/fixed-trace-probe/splice-output.txt"
                        and t["bytes_transferred"] == 16]
        transfer_coverage = all(transfer_refs.values()) and bool(splice_read and splice_write)
        transfer_coverage = transfer_coverage and all(
            checks.get("file_transfer_checks", {}).get(kind) is True
            for kind in ("sendfile", "copy_file_range", "splice"))
        report["fixed_transfer_probe"] = {
            "passed": transfer_coverage, "native_references": transfer_refs,
            "splice_source_references": splice_read, "splice_sink_references": splice_write,
            "scope": "Known fake-file transfers; pipe/socket peers and general flow incomplete",
            "complete": False,
        }
        async_kinds = ("io_uring_setup", "io_uring_enter", "io_uring_register")
        async_refs = {kind: [f"sysdig:{r['evt.num']}" for r in events
                            if r["evt.type"] == kind and r["evt.dir"] == "<"
                            and r.get("evt.rawres") == -1] for kind in async_kinds}
        async_denied = all(async_refs.values()) and all(
            checks.get("io_uring_checks", {}).get(kind) == {"result": -1, "errno": 1}
            for kind in async_kinds)
        report["fixed_async_probe"] = {
            "denials_verified": async_denied, "native_references": async_refs,
            "scope": "Known calls denied under combined native controls; no async I/O submitted",
            "complete": False,
        }
        mutation_root = "/sandbox/fixed-trace-probe/"
        mutation_expected = {
            "exclusive_create": ("exclusive-empty.txt", "exclusive_create"),
            "open_truncate": ("truncated.txt", "open_truncate"),
            "rename": ("rename-target.txt", "rename"),
            "hardlink": ("hardlink.txt", "link"),
            "symlink": ("symlink.txt", "symlink"),
            "unlink": ("removed.txt", "unlink"),
            "mkdir": ("removed-directory", "mkdir"),
            "rmdir": ("removed-directory", "rmdir"),
        }
        mutation_refs = {
            name: [m for m in evidence.file_mutations
                   if mutation_root + filename in m["paths"] and m["action"] == action
                   and m["actual_mutation"]]
            for name, (filename, action) in mutation_expected.items()
        }
        possible_existing = [m for m in evidence.file_mutations
                             if mutation_root + "existing-create.txt" in m["paths"]
                             and m["action"] == "possible_create" and not m["actual_mutation"]]
        mutation_coverage = (all(mutation_refs.values()) and bool(possible_existing)
                             and bool(checks.get("file_mutation_checks"))
                             and all(v is True for v in checks["file_mutation_checks"].values()))
        report["fixed_file_mutation_probe"] = {
            "passed": mutation_coverage, "native_references": mutation_refs,
            "existing_create_references": possible_existing,
            "scope": "Known fictional paths; actual changes separate from possible creation",
            "complete": False,
        }
        metadata_expected = {
            "path_permissions": ("metadata-file.txt", "fchmodat"),
            "descriptor_permissions": ("metadata-file.txt", "fchmod"),
            "path_ownership": ("metadata-file.txt", "fchownat"),
            "descriptor_ownership": ("metadata-file.txt", "fchown"),
            "symlink_ownership": ("symlink.txt", "fchownat"),
        }
        metadata_refs = {
            name: [m for m in evidence.file_mutations
                   if m["kind"] == kind and m["paths"] == [mutation_root + filename]]
            for name, (filename, kind) in metadata_expected.items()
        }
        metadata_checks = checks.get("file_metadata_checks", {})
        metadata_coverage = (all(len(refs) == 1 for refs in metadata_refs.values())
            and set(metadata_checks) == set(metadata_expected) | {"content_unchanged"}
            and all(value is True for value in metadata_checks.values()))
        report["fixed_file_metadata_probe"] = {
            "passed": metadata_coverage, "native_references": metadata_refs,
            "scope": "Native applied metadata operations; aliases and symlink flags incomplete",
            "complete": False,
        }
        coverage = (
            "/sandbox/fixed-trace-probe/receipt.txt" in evidence.envelope.files_read
            and "/sandbox/fixed-trace-probe/output.txt" in evidence.envelope.files_written
            and "/usr/bin/echo" in evidence.envelope.processes
            and f"127.0.0.1:{probe['operator_listener_port']}" in evidence.envelope.network_hosts
            and len(escaped_write) == 1
            and mmap_coverage
            and lifecycle_coverage
            and transfer_coverage
            and mutation_coverage
            and metadata_coverage
            and async_denied
            and (not args.capture_startup or len(startup_write) == 1)
        )
        restrictions = (
            checks.get("uid") == 1000 and checks.get("cap_eff") == "0000000000000000"
            and checks.get("no_new_privs") == "1" and checks.get("seccomp") == "2"
            and checks.get("ptrace_result") == -1 and checks.get("ptrace_errno") == 1
            and checks.get("provider_credentials_present") is False
            and checks.get("host_canary_visibility", {}).get("visible") is False
            and checks.get("observer_log_visibility", {}).get("visible") is False
        )
        failures = capture_failures(active=report["collector_active_after_probe"],
                                    stats=stats, coverage=coverage)
        passed = (not failures and restrictions and checks.get("functional_passed") is True
                  and checks.get("clone_untraced_marker_correct") is True
                  and probe.get("stopped_phase") == "Stopped"
                  and probe.get("operator_canary_unchanged") is True
                  and probe.get("operator_listener_received_connection") is False)
        report.update({
            "fixed_probe_passed": passed, "coverage_markers_passed": coverage,
            "capture_failure_reasons": failures,
            "startup_write_event": [row["evt.num"] for row in startup_write],
            "startup_capture_verified": args.capture_startup and passed,
            "restrictions_verified": restrictions, "native_stats": stats,
            "container_id": container["id"], "image_id": container["image"],
            "probe_sha256": probe["probe_sha256"], "scoped_events": evidence.scoped_events,
            "escaped_child_write_event": [row["evt.num"] for row in escaped_write],
            "strace_missed_escaped_write": omitted_by_strace,
            "unresolved_events": evidence.unresolved_events,
            "workload_checks": checks, "sandbox_stopped": probe.get("stopped_phase") == "Stopped",
            "payload_snaplen": 1,
        })
        if prepared:
            candidate = report["candidate_execution"]
            candidate["program_read_refs"] = evidence.event_refs.get(
                "files_read:/opt/skillguard-candidate/scripts/parse_receipt.py", [])
            candidate["input_read_refs"] = evidence.event_refs.get(
                "files_read:/opt/skillguard-fixtures/input.txt", [])
            candidate["output_write_refs"] = evidence.event_refs.get(
                "files_written:/sandbox/receipt-output.json", [])
            candidate["native_activity_observed"] = all(candidate[key] for key in (
                "program_read_refs", "input_read_refs", "output_write_refs"))
        state = report.get("collector_loss_state", {})
        report["collector_loss_verified"] = (
            args.simulate_collector_loss and state.get("ExecMainCode") == "2"
            and state.get("ExecMainStatus") == "9" and state.get("Result") == "signal"
            and not report["collector_active_after_probe"] and stats is None and not coverage
            and checks.get("functional_passed") is True and restrictions
            and probe.get("stopped_phase") == "Stopped"
            and probe.get("operator_canary_unchanged") is True
            and probe.get("operator_listener_received_connection") is False
        )
    except Exception as error:
        report["error"] = str(error)
    finally:
        if collector_started:
            native(["systemctl", "stop", unit], check=False)
        native(["openshell", "sandbox", "stop", args.sandbox], check=False)
        stop = subprocess.run(["limactl", "stop", args.vm], capture_output=True,
                              text=True, env=env, timeout=60)
        (run / "runner-stop.txt").write_text(stop.stdout + stop.stderr)
        status = subprocess.run(["limactl", "list", "--json"], capture_output=True,
                                text=True, env=env, check=True, timeout=30)
        instances = [json.loads(line) for line in status.stdout.splitlines() if line.strip()]
        report["runner_stopped"] = any(row["name"] == args.vm and row["status"] == "Stopped"
                                       for row in instances)
        report["wall_seconds"] = round(time.monotonic() - started, 3)
        report["limitations"] = [
            ("Known pending parser execution" if args.prepared_parser
             else "Fixed fake-data probe only"),
            "No arbitrary-candidate replay or Skill Lift",
            "Native startup captured" if args.capture_startup else "Post-startup capture window",
            "Full arbitrary-candidate failure coverage unverified",
            "Zero native driver drops does not establish complete event capture",
            "Adapter covers completed file I/O/exec and connect attempts, not every syscall",
            "Refused mediated connects can lack destinations; unresolved events remain explicit",
            "Snaplen 0 retained payloads in the earlier trial; this trial uses snaplen 1",
        ]
        report["artifacts"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in run.iterdir() if path.is_file()}
        output = json.dumps(report, indent=2) + "\n"
        (run / "backend.json").write_text(output)
        (root / "results/kernel-backend-latest.json").write_text(output)
        if args.prepared_parser and report.get("candidate_execution") and not report.get("error"):
            try:
                from skillguard.review.store import ReviewStore
                candidate = report["candidate_execution"]
                store = ReviewStore(Path(candidate["store"]))
                store.record_candidate_execution_probe(candidate["review_id"],
                    report=output.encode(), artifacts={
                        name: (run / name).read_bytes() for name in report["artifacts"]
                        if name != "events.scap"})
                if args.compare_control:
                    store.record_candidate_process_comparison(candidate["review_id"],
                        report=output.encode(), artifacts={
                            name: (run / name).read_bytes() for name in report["artifacts"]
                            if name != "events.scap"})
                report["review_decision"] = store.decide(candidate["review_id"])
                report["candidate_review_recorded"] = True
            except Exception as error:
                report["review_error"] = str(error)
                report["candidate_review_recorded"] = False
            output = json.dumps(report, indent=2) + "\n"
            (run / "backend.json").write_text(output)
            (root / "results/kernel-backend-latest.json").write_text(output)
        for path in run.iterdir():
            if path.is_file():
                path.chmod(0o600)
        print(output)
    expected = "collector_loss_verified" if args.simulate_collector_loss else "fixed_probe_passed"
    if not report.get(expected) or not report.get("runner_stopped"):
        raise SystemExit(2)
    if args.prepared_parser and not report.get("candidate_review_recorded"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
