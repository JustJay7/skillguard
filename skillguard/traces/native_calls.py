"""Conservative pairing of supplied native syscall metadata; no capture service."""

from __future__ import annotations

from dataclasses import dataclass, field


def native_thread_identity(row: dict) -> tuple[int, int, int] | None:
    values = tuple(row.get(name) for name in ("proc.pid", "proc.pid.ts", "thread.tid"))
    return values if all(type(v) is int and v > 0 for v in values) else None


def native_file_path(fd: object) -> str | None:
    return fd[3:] if isinstance(fd, str) and fd.startswith("<f>/") and "\0" not in fd else None


@dataclass
class NativeCallPairs:
    kinds: frozenset[str]
    minimum_result: int
    gaps: dict[str, str] = field(default_factory=dict)
    pending: dict[tuple[int, int, int], dict] = field(default_factory=dict)
    ambiguous: set[tuple[int, int, int]] = field(default_factory=set)

    def gap(self, row: dict, detail: str) -> None:
        self.gaps[f"sysdig:{row['evt.num']}"] = (
            row["evt.type"] + " access not represented; " + detail)

    def consume(self, row: dict) -> dict | None:
        kind, direction, key = row["evt.type"], row["evt.dir"], native_thread_identity(row)
        if kind == "procexit":
            if key in self.pending:
                self.gap(self.pending.pop(key), "thread exited without observed completion")
            self.ambiguous.discard(key)
            return None
        if kind not in self.kinds:
            return None
        if direction == "<":
            result = row.get("evt.rawres")
            if type(result) is not int:
                raise ValueError("Missing or invalid native " + kind + " return value")
            if result < self.minimum_result:
                self.pending.pop(key, None)
                self.ambiguous.discard(key)
                return None
        if key is None:
            self.gap(row, "native process/thread identity unresolved")
            return None
        if direction == ">":
            if key in self.pending:
                self.gap(self.pending[key], "ambiguous nested native entry")
                self.gap(row, "ambiguous nested native entry")
                self.ambiguous.add(key)
            self.pending[key] = row
            return None
        entry = self.pending.pop(key, None)
        ambiguous = key in self.ambiguous
        self.ambiguous.discard(key)
        if (entry is None or ambiguous or entry["evt.type"] != kind
                or entry["evt.num"] >= row["evt.num"]
                or entry["evt.rawtime"] > row["evt.rawtime"]):
            self.gap(row, "native entry missing or ambiguous")
            return None
        return entry

    def finish(self) -> None:
        for row in self.pending.values():
            self.gap(row, "native completion missing")
