"""Adapt existing Sysdig JSON metadata into a partial behavioral envelope.

This module neither captures events nor establishes collector authenticity or
completeness. Native Sysdig resolves file descriptors and executable paths; we
adapt completed I/O/exec and separate mapping permissions in one full container.
Network endpoints represent attempts, including refused/in-progress connections.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field

from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.traces.file_mutations import MUTATION_FIELDS, MUTATION_KINDS, NativeFileMutations
from skillguard.traces.mappings import NativeMappings
from skillguard.traces.socket_io import SOCKET_KINDS, NativeSocketIO
from skillguard.traces.transfers import TRANSFER_FIELDS, TRANSFER_KINDS, NativeTransfers


def capture_failures(*, active: object, stats: object, coverage: object) -> list[str]:
    """Conservative negative checks on a bounded native capture report.

    An empty result is only fixed-probe health, never proof of completeness,
    authenticity, candidate identity or capture of every relevant operation.
    """
    failures = []
    if active is not True:
        failures.append("Native collector stopped before the fixed probe finished")
    fields = ("driver_events", "captured_events", "driver_drops", "suppressed_comm")
    if not isinstance(stats, dict) or any(
        type(stats.get(key)) is not int or stats[key] < 0 for key in fields
    ):
        failures.append("Native final capture statistics missing or invalid")
    else:
        if stats["driver_drops"] or stats["suppressed_comm"]:
            failures.append("Native capture dropped or suppressed events")
        if not stats["driver_events"] or not stats["captured_events"]:
            failures.append("Native capture recorded no events")
    if coverage is not True:
        failures.append("Fixed probe coverage markers missing")
    return failures


SYSDIG_FORMAT = (
    "*%evt.num %evt.rawtime %proc.pid %proc.ppid %proc.exepath %thread.tid "
    "%thread.vtid %container.id %container.full_id %evt.type %evt.dir "
    "%evt.rawres %fd.type %fd.name %fd.sip %fd.sport %proc.pid.ts "
    "%evt.arg.fd %evt.arg.prot %evt.arg.flags"
) + TRANSFER_FIELDS + MUTATION_FIELDS + (
    " %evt.arg.addr %evt.arg.length %fd.num %fd.l4proto %fd.is_server"
    " %fd.cip %fd.cport %fd.rip %fd.rport %evt.arg.tuple"
    " %fd.dev %fd.dev.major %fd.dev.minor %fd.ino %evt.arg.dev %evt.arg.ino"
)

_READS = {"read", "pread", "readv", "preadv", "preadv2"}
_WRITES = {"write", "pwrite", "writev", "pwritev", "pwritev2"}
_EXECS = {"execve", "execveat"}
_UNHANDLED_SETUP = {"io_uring_setup", "io_uring_enter", "io_uring_register"}


@dataclass
class SysdigEvidence:
    envelope: BehavioralEnvelope = field(default_factory=BehavioralEnvelope)
    event_refs: dict[str, list[str]] = field(default_factory=dict)
    observed_event_types: set[str] = field(default_factory=set)
    unresolved_events: dict[str, str] = field(default_factory=dict)
    scoped_events: int = 0
    complete: bool = False
    memory_mappings: list[dict] = field(default_factory=list)
    mapping_changes: list[dict] = field(default_factory=list)
    anonymous_mappings: int = 0
    file_transfers: list[dict] = field(default_factory=list)
    file_mutations: list[dict] = field(default_factory=list)
    directory_opens: list[dict] = field(default_factory=list)
    socket_io: list[dict] = field(default_factory=list)

    @property
    def path_mutation_capabilities(self) -> BehavioralEnvelope:
        """Possible creation via O_CREAT, separate from actual filesystem changes."""
        return BehavioralEnvelope(files_written={
            path for m in self.file_mutations if not m["actual_mutation"] for path in m["paths"]
        })

    @property
    def mapping_capabilities(self) -> BehavioralEnvelope:
        """Declared readable/shared-writable mappings, not completed byte I/O."""
        return BehavioralEnvelope(
            files_read={m["path"] for m in self.memory_mappings if m["readable"]},
            files_written={m["path"] for m in self.memory_mappings
                           if m["writable"] and m["shared"]},
        )

    def reference(self, kind: str, value: str, number: int) -> None:
        self.event_refs.setdefault(f"{kind}:{value}", []).append(f"sysdig:{number}")


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"Missing or invalid native {label}")
    return value


def _path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or "\0" in value:
        raise ValueError(f"Missing or unresolved native {label}")
    return value


def parse_sysdig_stats(text: str) -> dict[str, int]:
    """Read native end-of-capture counters; zero drops is not completeness."""
    patterns = {
        "driver_events": r"Driver Events:(\d+)",
        "driver_drops": r"Driver Drops:(\d+)",
        "suppressed_comm": r"Suppressed by Comm:(\d+)",
        "captured_events": r"Captured Events: (\d+)",
    }
    result = {}
    for name, pattern in patterns.items():
        values = re.findall(pattern, text)
        if len(values) != 1:
            raise ValueError(f"Missing or ambiguous native capture counter: {name}")
        result[name] = int(values[0])
    return result


def parse_sysdig(text: str, *, container_id: str) -> SysdigEvidence:
    """Read metadata exported with SYSDIG_FORMAT; never grant completeness.

    The native formatter's leading '*' is required: without it, missing network
    fields silently suppress file events. Preserve JSON nulls for optional fields.
    Foreign containers are excluded; target events without full identity fail.
    File mappings are separate permission facts, not completed I/O or page access.
    File-copy paths come from paired native descriptor metadata and positive byte
    counts; unresolved pipe/socket endpoints remain gaps, even with a known file.
    Opens, failed reads, EOF and file metadata cannot establish absence.
    """
    if not re.fullmatch(r"[a-f0-9]{64}", container_id):
        raise ValueError("Expected full native container ID")
    result = SysdigEvidence()
    values: dict[str, set[str]] = {
        name: set() for name in ("files_read", "files_written", "processes", "network_hosts")
    }
    seen: set[int] = set()
    mappings = NativeMappings()
    transfers = NativeTransfers()
    mutations = NativeFileMutations()
    sockets = NativeSocketIO()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid native JSON event on line {line_number}") from error
        if not isinstance(row, dict):
            raise ValueError("Native event must be an object")
        if row.get("container.id") != container_id[:12]:
            continue
        number = _integer(row.get("evt.num"), "event number")
        if number < 1 or number in seen:
            raise ValueError("Invalid or duplicate scoped native event number")
        seen.add(number)
        _integer(row.get("evt.rawtime"), "timestamp")
        kind = row.get("evt.type")
        if not isinstance(kind, str) or not kind:
            raise ValueError("Missing native event type")
        if row.get("container.full_id") != container_id:
            if (row.get("container.full_id") is None
                    and kind not in _READS | _WRITES | _EXECS | SOCKET_KINDS | {"connect"}):
                # Native container removal can invalidate enrichment on teardown.
                # Such records never contribute facts and remain an explicit gap.
                result.unresolved_events[f"sysdig:{number}"] = "unbound native metadata event"
                continue
            raise ValueError("Target event lacks exact native container identity")
        result.scoped_events += 1
        result.observed_event_types.add(kind)
        direction = row.get("evt.dir")
        if direction not in {"<", ">"}:
            raise ValueError("Missing native event direction")
        socket_io = sockets.consume(row)
        if socket_io and socket_io['peer_endpoint']:
            endpoint = socket_io['peer_endpoint']
            category = 'network_writes' if socket_io['direction'] == 'outgoing' else 'network_reads'
            result.reference(category, endpoint, number)
            if socket_io['direction'] == 'outgoing':
                values['network_hosts'].add(endpoint)
        mappings.consume(row)
        mutation = mutations.consume(row)
        if kind in MUTATION_KINDS:
            if mutation and mutation["actual_mutation"]:
                for path in mutation["paths"]:
                    values["files_written"].add(path)
                    result.reference("files_written", path, number)
            continue
        transfer = transfers.consume(row)
        if kind in TRANSFER_KINDS:
            if transfer:
                for category, path in (("files_read", transfer["source_file"]),
                                       ("files_written", transfer["destination_file"])):
                    if path is not None:
                        values[category].add(path)
                        result.reference(category, path, number)
            continue
        if kind in {"mmap", "mmap2", "mprotect", "munmap", "mremap", "pkey_mprotect"}:
            continue
        if kind in _UNHANDLED_SETUP and direction == "<":
            raw_result = _integer(row.get("evt.rawres"), kind + " return value")
            if raw_result >= 0:
                detail = "source/destination or asynchronous access unresolved"
                result.unresolved_events[f"sysdig:{number}"] = (
                    f"{kind} access not represented; {detail}"
                )
            continue
        if direction == ">" or kind not in _READS | _WRITES | _EXECS | {"connect"}:
            continue
        _integer(row.get("proc.pid"), "process ID")
        raw_result = _integer(row.get("evt.rawres"), "return value")
        if kind in _READS | _WRITES:
            if raw_result <= 0 or row.get("fd.type") != "file":
                continue
            if isinstance(row.get("fd.name"), str) and row["fd.name"].startswith("<UNKNOWN>"):
                # Native runc startup can resolve an FD relative to an unknown
                # process root. Preserve the gap; never invent an absolute path.
                result.unresolved_events[f"sysdig:{number}"] = "native file path root unresolved"
                continue
            path = _path(row.get("fd.name"), "file path")
            category = "files_read" if kind in _READS else "files_written"
            values[category].add(path)
            result.reference(category, path, number)
        elif kind in _EXECS and raw_result == 0:
            path = _path(row.get("proc.exepath"), "executable path")
            values["processes"].add(path)
            result.reference("processes", path, number)
        elif kind == "connect" and row.get("fd.type") in {"ipv4", "ipv6"}:
            if row.get("fd.sip") is None or row.get("fd.sport") is None:
                # Native denial/mediation can leave no resolved FD destination.
                # Keep this explicit gap; never infer absence or an endpoint.
                result.unresolved_events[f"sysdig:{number}"] = "connect destination unresolved"
                continue
            try:
                address = ipaddress.ip_address(row.get("fd.sip"))
            except (ValueError, TypeError) as error:
                raise ValueError("Missing native connect destination") from error
            port = _integer(row.get("fd.sport"), "destination port")
            if not 1 <= port <= 65535:
                raise ValueError("Invalid native destination port")
            host = f"[{address}]" if address.version == 6 else str(address)
            endpoint = f"{host}:{port}"
            values["network_hosts"].add(endpoint)
            result.reference("network_attempts", endpoint, number)
    if result.scoped_events == 0:
        raise ValueError("No events from exact target container")
    mappings.finish()
    transfers.finish()
    result.memory_mappings = mappings.mappings
    result.mapping_changes = mappings.changes
    result.anonymous_mappings = mappings.anonymous
    result.unresolved_events.update(mappings.gaps)
    result.unresolved_events.update(transfers.gaps)
    result.unresolved_events.update(mutations.gaps)
    result.unresolved_events.update(sockets.gaps)
    result.file_mutations = mutations.mutations
    result.directory_opens = mutations.directory_opens
    result.socket_io = sockets.operations
    result.file_transfers = transfers.transfers
    result.envelope = BehavioralEnvelope(**values)
    return result
