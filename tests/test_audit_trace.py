import socket
import socketserver
import subprocess
import threading
from pathlib import Path

from skillguard.traces.audit import AuditTracer


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.recv(16)


def test_python_audit_tracer_captures_safe_runtime_behavior(tmp_path: Path) -> None:
    invoice = tmp_path / "invoice.txt"
    private = tmp_path / "private.txt"
    out = tmp_path / "out.txt"
    invoice.write_text("invoice")
    private.write_text("fake-canary-secret")

    with socketserver.TCPServer(("127.0.0.1", 0), _Handler) as server:
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        port = server.server_address[1]

        tracer = AuditTracer()
        with tracer.capture():
            invoice.read_text()
            private.read_text()
            out.write_text("done")
            subprocess.run(["/bin/echo", "ok"], check=True, stdout=subprocess.DEVNULL)
            with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
                client.sendall(b"canary")

        thread.join(timeout=1)

    envelope = tracer.envelope()
    assert str(invoice) in envelope.files_read
    assert str(private) in envelope.files_read
    assert str(out) in envelope.files_written
    assert f"127.0.0.1:{port}" in envelope.network_hosts
    assert "/bin/echo" in envelope.processes
