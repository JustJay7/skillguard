from __future__ import annotations

import argparse
import codecs
import importlib.util
import json
import socketserver
import tempfile
import threading
from pathlib import Path
from types import ModuleType

from skillguard.envelope.diff import diff_envelopes
from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.review.store import snapshot_digest
from skillguard.traces.audit import AuditTracer


class CanaryHandler(socketserver.BaseRequestHandler):
    received = b""

    def handle(self) -> None:
        type(self).received = self.request.recv(4096)


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    # Executing a fixture must not add bytecode artifacts to the skill being scanned.
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Controlled fixture replay; run inside OpenShell")
    parser.add_argument("--baseline", type=Path, default=root / "skills/benign/invoice-organizer")
    parser.add_argument(
        "--candidate", type=Path, default=root / "skills/planted/poisoned-invoice-organizer"
    )
    parser.add_argument("--output", type=Path, default=root / "results")
    args = parser.parse_args()
    baseline_sha = snapshot_digest(args.baseline)
    candidate_sha = snapshot_digest(args.candidate)
    benign = load_module(args.baseline / "scripts/run.py", "benign_invoice_skill")
    planted = load_module(
        args.candidate / "scripts/run.py",
        "planted_invoice_skill",
    )

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        invoice = work / "invoice.txt"
        fake_secret = work / "fake-secret.txt"
        invoice.write_text("invoice-42")
        fake_secret.write_text("FAKE_CANARY_SECRET")
        # Give both runs the same import state and output path; do not filter evidence.
        codecs.lookup("idna")
        output = work / "out.txt"

        benign_trace = AuditTracer()
        with benign_trace.capture():
            benign.run(str(invoice), str(output))
        assert output.read_text() == "processed:invoice-42", "benign task output failed"

        CanaryHandler.received = b""
        with socketserver.TCPServer(("127.0.0.1", 0), CanaryHandler) as server:
            thread = threading.Thread(target=server.handle_request, daemon=True)
            thread.start()
            host, port = server.server_address
            planted_trace = AuditTracer()
            with planted_trace.capture():
                planted.run(
                    str(invoice),
                    str(output),
                    str(fake_secret),
                    host,
                    port,
                )
            thread.join(timeout=1)
            assert CanaryHandler.received == b"FAKE_CANARY_SECRET", "canary receipt not verified"
            assert output.read_text() == "processed:invoice-42", "planted task output failed"

        assert snapshot_digest(args.baseline) == baseline_sha, "baseline changed during replay"
        assert snapshot_digest(args.candidate) == candidate_sha, "candidate changed during replay"
        result_dir = args.output
        result_dir.mkdir(parents=True, exist_ok=True)
        before = benign_trace.envelope()
        after = planted_trace.envelope()
        diff = diff_envelopes(before, after)
        (result_dir / "local_smoke_before.json").write_text(
            json.dumps(before.to_dict(), indent=2, sort_keys=True)
        )
        (result_dir / "local_smoke_after.json").write_text(
            json.dumps(after.to_dict(), indent=2, sort_keys=True)
        )
        (result_dir / "local_smoke_diff.json").write_text(
            json.dumps(diff.to_dict(), indent=2, sort_keys=True)
        )
        checks = {
            "baseline_sha256": baseline_sha,
            "candidate_sha256": candidate_sha,
            "functional_passed": True,
            "fake_canary_received": True,
            "operator_contract": BehavioralEnvelope(
                files_read=[str(invoice)], files_written=[str(output)]
            ).to_dict(),
        }
        (result_dir / "local_smoke_checks.json").write_text(json.dumps(checks, indent=2) + "\n")
        print(json.dumps(diff.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
