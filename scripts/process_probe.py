"""Known-safe process evidence probe; run inside the configured isolation backend."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from skillguard.traces.audit import AuditTracer


def main() -> None:
    tracer = AuditTracer()
    with tracer.capture():
        result = subprocess.run(
            ["/bin/echo", "FAKE_PROCESS_PROBE"], check=True, capture_output=True
        )
    assert result.stdout.strip() == b"FAKE_PROCESS_PROBE"
    envelope = tracer.envelope()
    assert "/bin/echo" in envelope.processes
    evidence = json.dumps(envelope.to_dict(), indent=2) + "\n"
    root = Path(__file__).resolve().parents[1]
    (root / "results/process_probe.json").write_text(evidence)
    print(evidence)


if __name__ == "__main__":
    main()
