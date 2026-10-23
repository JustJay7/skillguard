"""Verify Hermes' existing SSH environment against a fresh OpenShell VM.

No model, candidate code, profile sync, custom harness or monitoring service.
The only adapter adds an isolated SSH config file to native command arguments.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

from scripts.hermes_review_probe import command
from skillguard.intercept.reconstruct import HermesReconstructor


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root.parent / "work/hermes-agent"
    HermesReconstructor(source)
    sys.path.insert(0, str(source))
    from agent.terminal_env_provider import TerminalEnvironmentProvider
    from agent.terminal_env_registry import register_provider, restore_registration
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.environments.remote_common import resolve_passthrough_env
    from tools.environments.ssh import SSHEnvironment
    from tools.terminal_scope import reset_terminal_scope, set_terminal_scope
    from tools.terminal_tool import terminal_tool
    from tools.terminal_tool_lifecycle import cleanup_vm

    suffix = uuid.uuid4().hex[:8]
    name = f"sg-ssh-{suffix}"
    run = root / "results/integration" / f"ssh-backend-{suffix}"
    profile = run / "hermes-profile"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text(
        "skills:\n  write_approval: true\nterminal:\n  env_passthrough: []\n"
    )
    host_only = run / "host-only-fake-canary.txt"
    host_only.write_text("FAKE_HOST_ONLY_CANARY")
    config = run / "ssh_config"
    token, environment = set_hermes_home_override(profile), None
    created, outcome = False, None
    provider, scope_token, report = None, None, None
    try:
        values, _ = resolve_passthrough_env()
        if values:
            raise RuntimeError("test profile unexpectedly forwards environment values")
        command([
            "openshell", "sandbox", "create", "--name", name,
            "--from", "python:3.12-slim", "--detach", "--no-auto-providers",
            "--", "sleep", "3600",
        ], run / "create.txt")
        created = True
        command(["openshell", "sandbox", "ssh-config", name], config)
        config.chmod(0o600)
        lines = config.read_text().splitlines()
        hosts = [line.split()[1] for line in lines if line.startswith("Host ")]
        if len(hosts) != 1 or not hosts[0].startswith(f"openshell-{name}."):
            raise RuntimeError("unexpected native SSH host entry")
        config_sha = hashlib.sha256(config.read_bytes()).hexdigest()

        class IsolatedConfigSSH(SSHEnvironment):
            def _build_ssh_command(self, extra_args=None, send_env=()):
                if hashlib.sha256(config.read_bytes()).hexdigest() != config_sha:
                    raise RuntimeError("operator SSH configuration changed")
                args = super()._build_ssh_command(extra_args, send_env)
                return args[:1] + ["-F", str(config)] + args[1:]

        environment = IsolatedConfigSSH(
            host=hosts[0], user="sandbox", cwd="/sandbox",
            timeout=30, sync_files=False,
        )

        class OpenShellProbeProvider(TerminalEnvironmentProvider):
            name = "skillguard_openshell_probe"

            def is_available(self):
                return config.is_file()

            def create_environment(self, **kwargs):
                # Reuse the authenticated native instance; do not create a second VM.
                return environment

        provider = OpenShellProbeProvider()
        register_provider(provider, scope=str(profile.resolve()))
        scope_token = set_terminal_scope({
            "TERMINAL_ENV": provider.name, "TERMINAL_CWD": "/sandbox",
            "TERMINAL_TIMEOUT": "30", "TERMINAL_PERSISTENT": "false",
        })
        probe = """
import json, os, platform
from pathlib import Path
root=Path('/sandbox/backend-check')
root.mkdir(exist_ok=True)
(root/'receipt.txt').write_text('Maple Corner Cafe: CAD 13.80')
(root/'output.txt').write_text('processed:'+ (root/'receipt.txt').read_text())
print(json.dumps({
 'os':platform.system(), 'uid':os.getuid(),
 'functional_passed':(root/'output.txt').read_text()=='processed:Maple Corner Cafe: CAD 13.80',
 'host_canary_visible':Path(HOST_PATH).exists(),
 'provider_credentials_present':any(os.environ.get(k) for k in
   ['NEBIUS_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','NVIDIA_API_KEY']),
}))
""".replace("HOST_PATH", repr(str(host_only.resolve())))
        outcome = environment.execute("python -c " + shlex.quote(probe), timeout=30)
        (run / "native-execute.json").write_text(json.dumps(outcome, indent=2) + "\n")
        if outcome["returncode"] != 0:
            raise RuntimeError("native SSH environment execution failed")
        checks = json.loads(outcome["output"])
        assert checks["os"] == "Linux" and checks["uid"] == 1000
        assert checks["functional_passed"] is True
        assert checks["host_canary_visible"] is False
        assert checks["provider_credentials_present"] is False
        assert host_only.read_text() == "FAKE_HOST_ONLY_CANARY"
        tool_outcome = json.loads(terminal_tool(
            "python -c " + shlex.quote(probe), timeout=30, task_id=run.name,
        ))
        (run / "native-terminal-tool.json").write_text(json.dumps(tool_outcome, indent=2) + "\n")
        if tool_outcome.get("exit_code") != 0:
            raise RuntimeError("native terminal tool failed; see saved result")
        tool_checks = json.loads(tool_outcome["output"])
        if tool_checks != checks:
            raise RuntimeError("native terminal tool and direct SSH results differ")
        command(["openshell", "sandbox", "get", name, "-o", "json"], run / "native-sandbox.json")
        command(["openshell", "logs", name, "-n", "2000"], run / "native-logs.txt")
        report = {
            "run_id": run.name, "sandbox": name, "checks": checks,
            "native_environment": "Hermes SSHEnvironment with per-run -F config",
            "sync_files": False, "passthrough_values": False,
            "ssh_config_sha256": config_sha, "model_calls": 0,
            "native_terminal_tool_passed": True,
            "limitations": [
                "Terminal environment test only; full AIAgent is not inside the VM",
                "No arbitrary candidate or generated code was executed",
                "Native shorthand logs are partial and can drop events",
                "Successful file reads and every child exec are not covered",
            ],
        }
    finally:
        try:
            cleanup_vm(run.name)
            if environment:
                environment.cleanup()
        finally:
            if provider:
                restore_registration(provider.name, provider, None, scope=str(profile.resolve()))
            if scope_token:
                reset_terminal_scope(scope_token)
            reset_hermes_home_override(token)
            if created:
                stop = subprocess.run(
                    ["openshell", "sandbox", "stop", name],
                    capture_output=True, text=True, timeout=60,
                )
                (run / "stop.txt").write_text(stop.stdout + stop.stderr)
                if stop.returncode:
                    raise RuntimeError("test VM cleanup failed; see saved stop output")
                command(["openshell", "sandbox", "get", name, "-o", "json"], run / "stopped.json")
                stopped = json.loads((run / "stopped.json").read_text())
                if stopped["phase"] != "Stopped":
                    raise RuntimeError("test VM did not reach Stopped")
                if report:
                    report["sandbox_stopped"] = True
                    (run / "backend.json").write_text(json.dumps(report, indent=2) + "\n")
                    (root / "results/ssh-backend-latest.json").write_text(
                        json.dumps(report, indent=2) + "\n"
                    )
                    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
