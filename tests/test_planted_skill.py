import importlib.util
import socketserver
import threading
from pathlib import Path
from types import ModuleType

from skillguard.envelope.diff import diff_envelopes
from skillguard.traces.audit import AuditTracer


class _CanaryHandler(socketserver.BaseRequestHandler):
    received = b""

    def handle(self) -> None:
        type(self).received = self.request.recv(4096)


def _load_module(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


def test_planted_skill_produces_obvious_behavioral_diff(tmp_path: Path) -> None:
    benign = _load_module(
        Path("skills/benign/invoice-organizer/scripts/run.py"), "benign_invoice_skill"
    )
    planted = _load_module(
        Path("skills/planted/poisoned-invoice-organizer/scripts/run.py"),
        "planted_invoice_skill",
    )

    invoice = tmp_path / "invoice.txt"
    fake_secret = tmp_path / "fake-secret.txt"
    benign_out = tmp_path / "benign-out.txt"
    planted_out = tmp_path / "planted-out.txt"
    invoice.write_text("invoice-42")
    fake_secret.write_text("FAKE_CANARY_SECRET")

    benign_trace = AuditTracer()
    with benign_trace.capture():
        benign.run(str(invoice), str(benign_out))

    with socketserver.TCPServer(("127.0.0.1", 0), _CanaryHandler) as server:
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        host, port = server.server_address

        planted_trace = AuditTracer()
        with planted_trace.capture():
            planted.run(str(invoice), str(planted_out), str(fake_secret), host, port)

        thread.join(timeout=1)

    diff = diff_envelopes(benign_trace.envelope(), planted_trace.envelope())

    assert str(fake_secret) in diff.added.files_read
    assert f"127.0.0.1:{port}" in diff.added.network_hosts
    assert _CanaryHandler.received == b"FAKE_CANARY_SECRET"
