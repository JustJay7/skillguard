from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from typing import Any

from skillguard.envelope.schema import BehavioralEnvelope


class AuditTracer:
    """Small Python-audit-hook tracer used for local development only.

    This is not the production sandbox tracer. It exists so envelope normalization and
    diffing can be exercised safely before OpenShell/strace are available.
    """

    def __init__(self) -> None:
        self._active = False
        self._installed = False
        self._files_read: set[str] = set()
        self._files_written: set[str] = set()
        self._network_hosts: set[str] = set()
        self._processes: set[str] = set()

    def _hook(self, event: str, args: tuple[Any, ...]) -> None:
        if not self._active:
            return

        if event == "open" and args:
            path = args[0]
            if isinstance(path, (str, os.PathLike)):
                path_str = os.fspath(path)
                mode = args[1] if len(args) > 1 else None
                flags = args[2] if len(args) > 2 else 0
                if self._is_write(mode, flags):
                    self._files_written.add(path_str)
                else:
                    self._files_read.add(path_str)
            return

        if event == "socket.connect" and len(args) >= 2:
            address = args[1]
            if isinstance(address, tuple) and len(address) >= 2:
                host, port = address[0], address[1]
                self._network_hosts.add(f"{host}:{port}")
            return

        if event == "subprocess.Popen" and args:
            executable = args[0]
            if executable:
                self._processes.add(os.fspath(executable))

    @staticmethod
    def _is_write(mode: Any, flags: Any) -> bool:
        if isinstance(mode, str) and any(marker in mode for marker in ("w", "a", "+", "x")):
            return True
        if isinstance(flags, int):
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            return bool(flags & write_flags)
        return False

    @contextlib.contextmanager
    def capture(self) -> Iterator[AuditTracer]:
        if not self._installed:
            sys.addaudithook(self._hook)
            self._installed = True
        self._active = True
        try:
            yield self
        finally:
            self._active = False

    def envelope(self) -> BehavioralEnvelope:
        return BehavioralEnvelope(
            files_read=self._files_read,
            files_written=self._files_written,
            network_hosts=self._network_hosts,
            processes=self._processes,
        )
