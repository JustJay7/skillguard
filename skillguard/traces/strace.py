from __future__ import annotations

import re

from skillguard.envelope.schema import BehavioralEnvelope

_EXECVE_RE = re.compile(r'execve\("(?P<path>[^"]+)"')
_OPENAT_RE = re.compile(
    r'openat\([^,]+,\s*"(?P<path>[^"]+)",\s*(?P<flags>[^)]+)\)'
)
_INET_RE = re.compile(
    r'sin_port=htons\((?P<port>\d+)\).*?inet_addr\("(?P<host>[^"]+)"\)'
)

_WRITE_MARKERS = ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND")


def parse_strace(text: str) -> BehavioralEnvelope:
    """Parse a narrow strace subset used by SkillGuard replay fixtures.

    This parser only records behavior explicitly present in the trace. It does not infer
    unobserved capabilities.
    """

    files_read: set[str] = set()
    files_written: set[str] = set()
    network_hosts: set[str] = set()
    processes: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        exec_match = _EXECVE_RE.search(line)
        if exec_match:
            processes.add(exec_match.group("path"))
            continue

        open_match = _OPENAT_RE.search(line)
        if open_match:
            path = open_match.group("path")
            flags = open_match.group("flags")
            if any(marker in flags for marker in _WRITE_MARKERS):
                files_written.add(path)
            else:
                files_read.add(path)
            continue

        inet_match = _INET_RE.search(line)
        if inet_match:
            network_hosts.add(f'{inet_match.group("host")}:{inet_match.group("port")}')

    return BehavioralEnvelope(
        files_read=files_read,
        files_written=files_written,
        network_hosts=network_hosts,
        processes=processes,
    )
