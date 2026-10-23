"""Pair native mapping metadata; preserve unbound permission/lifetime changes."""

from __future__ import annotations

from dataclasses import dataclass, field

from skillguard.traces.native_calls import NativeCallPairs, native_file_path, native_thread_identity


@dataclass
class NativeMappings:
    mappings: list[dict] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    anonymous: int = 0
    pairs: NativeCallPairs = field(default_factory=lambda: NativeCallPairs(
        frozenset({"mmap", "mmap2"}), 0))
    change_pairs: NativeCallPairs = field(default_factory=lambda: NativeCallPairs(
        frozenset({"mprotect", "munmap"}), 0))

    @property
    def gaps(self) -> dict[str, str]:
        return self.pairs.gaps | self.change_pairs.gaps

    def gap(self, row: dict, detail: str) -> None:
        self.pairs.gap(row, detail)

    def consume(self, row: dict) -> None:
        # These native catalog entries expose syscall IDs, not address arguments
        # or a usable result. Even a denial cannot be inferred from these rows.
        if row["evt.type"] in {"mremap", "pkey_mprotect"}:
            self.change_pairs.gap(row, "native generic event lacks mapping arguments/outcome")
            return
        change = self.change_pairs.consume(row)
        if row["evt.type"] in {"mprotect", "munmap"}:
            if change is not None:
                self.changes.append({
                    "kind": row["evt.type"], "address": change.get("evt.arg.addr"),
                    "length": change.get("evt.arg.length"),
                    "protection": change.get("evt.arg.prot"),
                    "entry_ref": f"sysdig:{change['evt.num']}",
                    "exit_ref": f"sysdig:{row['evt.num']}",
                    "process_identity": list(native_thread_identity(row)),
                    "backing_file": None, "page_access_observed": False,
                })
                self.change_pairs.gap(row, "backing ranges/lifetimes not reconstructed")
            return
        entry = self.pairs.consume(row)
        if entry is None:
            return
        prot, flags = entry.get("evt.arg.prot"), entry.get("evt.arg.flags")
        if not isinstance(prot, str) or not isinstance(flags, str) or not flags:
            self.gap(row, "native mapping protection/flags unresolved")
            return
        protections = set(prot.split("|"))
        if (not protections <= {"PROT_NONE", "PROT_READ", "PROT_WRITE", "PROT_EXEC", "0"}
                or (protections & {"PROT_NONE", "0"} and len(protections) != 1)):
            self.gap(row, "native mapping protection unsupported")
            return
        modes = set(flags.split("|"))
        if "MAP_ANONYMOUS" in modes:
            # Native fd -1 may format as EPERM. It is ignored by anonymous mmap;
            # the syscall's actual result is successful, and no backing file exists.
            self.anonymous += 1
            return
        if len(modes & {"MAP_PRIVATE", "MAP_SHARED"}) != 1:
            self.gap(row, "native file mapping mode unsupported")
            return
        path = native_file_path(entry.get("evt.arg.fd"))
        if path is None:
            self.gap(row, "backing file unresolved")
            return
        self.mappings.append({
            "path": path, "readable": "PROT_READ" in protections,
            "writable": "PROT_WRITE" in protections,
            "executable": "PROT_EXEC" in protections, "shared": "MAP_SHARED" in modes,
            "protection": prot, "flags": flags,
            "entry_ref": f"sysdig:{entry['evt.num']}", "exit_ref": f"sysdig:{row['evt.num']}",
            "process_identity": list(native_thread_identity(row)), "page_access_observed": False,
        })

    def finish(self) -> None:
        self.pairs.finish()
        self.change_pairs.finish()
