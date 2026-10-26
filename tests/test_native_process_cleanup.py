import asyncio
import contextlib
import json
import os
import signal
import sys
import time

import pytest

from scripts.harbor_openshell_environment import ReceiptOpenShellEnvironment


def test_native_timeout_does_not_wait_for_a_grandchild_holding_stdout(tmp_path):
    environment = object.__new__(ReceiptOpenShellEnvironment)
    environment.adapter_root = tmp_path
    child_pid = tmp_path / 'owned-child.pid'
    script = ('import subprocess,sys,time;from pathlib import Path;'
              'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);'
              'Path(sys.argv[1]).write_text(str(p.pid));time.sleep(30)')
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            asyncio.run(asyncio.wait_for(environment.native(
                [sys.executable, '-c', script, str(child_pid)], timeout=.5), timeout=2))
        assert time.monotonic() - started < 1.5
        reports = list(tmp_path.glob('timeout-*.json'))
        assert len(reports) == 1
        report = json.loads(reports[0].read_text())
        assert report['group_kill_requested'] and not report['cleanup_drain_timed_out']
    finally:
        if child_pid.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(child_pid.read_text()), signal.SIGKILL)
