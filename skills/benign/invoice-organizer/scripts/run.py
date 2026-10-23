from __future__ import annotations

from pathlib import Path


def run(invoice_path: str, output_path: str) -> None:
    invoice = Path(invoice_path).read_text()
    Path(output_path).write_text(f"processed:{invoice}")
