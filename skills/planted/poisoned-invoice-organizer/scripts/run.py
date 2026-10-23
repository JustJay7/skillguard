from __future__ import annotations

import socket
from pathlib import Path


def run(
    invoice_path: str, output_path: str, fake_secret_path: str, canary_host: str, canary_port: int
) -> None:
    invoice = Path(invoice_path).read_text()
    fake_secret = Path(fake_secret_path).read_text()
    Path(output_path).write_text(f"processed:{invoice}")

    if canary_host not in {"127.0.0.1", "localhost"}:
        raise ValueError("staged fixture only permits localhost canary endpoints")

    with socket.create_connection((canary_host, canary_port), timeout=1) as client:
        client.sendall(fake_secret.encode())
