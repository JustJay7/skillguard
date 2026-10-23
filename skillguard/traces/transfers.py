"""Adapt native completed zero-copy descriptors into partial file I/O facts."""

from __future__ import annotations

from dataclasses import dataclass, field

from skillguard.traces.native_calls import NativeCallPairs, native_file_path

TRANSFER_FIELDS = (" %evt.arg.in_fd %evt.arg.out_fd %evt.arg.fd_in %evt.arg.fd_out"
                   " %evt.arg.fdin %evt.arg.fdout")
TRANSFER_KINDS = frozenset({"sendfile", "splice", "copy_file_range"})


@dataclass
class NativeTransfers:
    transfers: list[dict] = field(default_factory=list)
    pairs: NativeCallPairs = field(default_factory=lambda: NativeCallPairs(TRANSFER_KINDS, 1))

    @property
    def gaps(self) -> dict[str, str]:
        return self.pairs.gaps

    def consume(self, row: dict) -> dict | None:
        entry = self.pairs.consume(row)
        if entry is None:
            return None
        kind = row["evt.type"]
        keys = {"sendfile": ("in_fd", "out_fd"), "splice": ("fd_in", "fd_out"),
                "copy_file_range": ("fdin", "fdout")}
        incoming, outgoing = keys[kind]
        source = native_file_path(entry.get("evt.arg." + incoming))
        target = native_file_path((row if kind == "copy_file_range" else entry).get(
            "evt.arg." + outgoing))
        if source is None or target is None:
            self.pairs.gap(row, "source/destination descriptor not a resolved regular file")
        transfer = {
            "kind": kind, "source_file": source, "destination_file": target,
            "bytes_transferred": row["evt.rawres"],
            "entry_ref": f"sysdig:{entry['evt.num']}", "exit_ref": f"sysdig:{row['evt.num']}",
            "complete": False,
        }
        self.transfers.append(transfer)
        return transfer

    def finish(self) -> None:
        self.pairs.finish()
