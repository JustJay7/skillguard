"""Adapt native filesystem changes separately from completed byte transfers.

Paths come from installed Sysdig fs.path fields, not caller argument resolution.
No alias canonicalization, inode lifetime reconstruction, collector or enforcer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

MUTATION_FIELDS = (
    " %fs.path.name %fs.path.source %fs.path.target %evt.is_open_create"
    " %evt.arg.mode %evt.arg.uid %evt.arg.gid"
)
OPENS = frozenset({"open", "openat", "openat2", "open_by_handle_at", "creat"})
SINGLE = frozenset({"unlink", "unlinkat", "rmdir", "mkdir", "mkdirat"})
DOUBLE = frozenset({"rename", "renameat", "renameat2", "link", "linkat"})
SYMLINKS = frozenset({"symlink", "symlinkat"})
METADATA_PATH = frozenset({"chmod", "fchmodat", "chown", "lchown", "fchownat"})
METADATA_FD = frozenset({"fchmod", "fchown"})
METADATA = METADATA_PATH | METADATA_FD
UNSUPPORTED = frozenset({
    "truncate", "ftruncate", "fallocate", "fchmodat2", "setxattr", "lsetxattr", "fsetxattr",
    "removexattr", "lremovexattr", "fremovexattr", "utime", "utimes", "utimensat",
})
MUTATION_KINDS = OPENS | SINGLE | DOUBLE | SYMLINKS | METADATA | UNSUPPORTED


def native_path(value: object) -> str | None:
    if (not isinstance(value, str) or not value.startswith("/") or "\0" in value
            or "<UNKNOWN>" in value or ".." in PurePosixPath(value).parts):
        return None
    return value


@dataclass
class NativeFileMutations:
    mutations: list[dict] = field(default_factory=list)
    gaps: dict[str, str] = field(default_factory=dict)
    directory_opens: list[dict] = field(default_factory=list)

    def consume(self, row: dict) -> dict | None:
        kind = row["evt.type"]
        if row["evt.dir"] != "<" or kind not in MUTATION_KINDS:
            return None
        ref = f"sysdig:{row['evt.num']}"
        result = row.get("evt.rawres")
        if type(result) is not int:
            self.gaps[ref] = f"{kind} outcome unresolved; filesystem change not represented"
            return None
        if result < 0:
            return None
        if kind in UNSUPPORTED:
            self.gaps[ref] = f"{kind} filesystem change not represented"
            return None
        if kind not in OPENS and result != 0:
            self.gaps[ref] = f"{kind} invalid native success result"
            return None
        paths, action, actual = [], kind, True
        if kind in OPENS:
            flags = row.get("evt.arg.flags")
            if kind == "creat":
                action = "create_or_truncate"
            elif not isinstance(flags, str):
                self.gaps[ref] = f"{kind} flags unresolved; possible filesystem change"
                return None
            else:
                flags = set(flags.split("|"))
                if "O_TMPFILE" in flags:
                    # Native 0.41.4 conflates the composite TMPFILE/DIRECTORY
                    # bits. Linux requires write access for a real O_TMPFILE.
                    # Preserve that writer as unresolved even if native fd.type
                    # incorrectly says directory (observed in the live control).
                    path = native_path(row.get('fd.name'))
                    readonly = {'O_RDONLY', 'O_DIRECTORY', 'O_TMPFILE'} <= flags
                    known = {'O_RDONLY', 'O_DIRECTORY', 'O_TMPFILE', 'O_CLOEXEC',
                             'O_NONBLOCK', 'O_NOFOLLOW', 'O_LARGEFILE',
                             'FD_LOWER_LAYER', 'FD_UPPER_LAYER'}
                    if (readonly and flags <= known and path is not None
                            and row.get('fd.type') == 'directory'
                            and row.get('fs.path.name') == path
                            and row.get('evt.arg.fd') == '<d>' + path):
                        self.directory_opens.append({'path': path, 'kind': kind,
                            'descriptor': result, 'exit_ref': ref,
                            'native_tmpfile_flag_conflict': True,
                            'byte_access_observed': False})
                        return None
                    self.gaps[ref] = f"{kind} unnamed temporary inode not represented"
                    return None
                if "O_TRUNC" in flags:
                    action = "open_truncate"
                elif {"O_CREAT", "O_EXCL"} <= flags:
                    action = "exclusive_create"
                elif "O_CREAT" in flags:
                    # O_CREAT can open an existing file. Do not claim creation.
                    action, actual = "possible_create", False
                else:
                    return None
            path = native_path(row.get("fs.path.name"))
            if path is None and row.get("fd.type") == "file":
                path = native_path(row.get("fd.name"))
            paths = [path]
        elif kind in METADATA:
            action = "permissions" if "chmod" in kind else "ownership"
            if kind in METADATA_FD:
                path = (native_path(row.get("fd.name"))
                        if row.get("fd.type") in {"file", "directory"} else None)
            else:
                path = native_path(row.get("fs.path.name"))
            paths = [path]
            names = ("mode",) if action == "permissions" else ("uid", "gid")
            if any(row.get("evt.arg." + name) is None for name in names):
                self.gaps[ref] = f"{kind} requested metadata unresolved"
        elif kind in DOUBLE:
            # Rename changes both entries; hardlink also changes source link count.
            action = "rename" if kind.startswith("rename") else "link"
            paths = [native_path(row.get("fs.path.source")),
                     native_path(row.get("fs.path.target"))]
        elif kind in SYMLINKS:
            # Native Sysdig source is the link entry; target is referenced text.
            action = "symlink"
            paths = [native_path(row.get("fs.path.source"))]
        else:
            action = "mkdir" if kind.startswith("mkdir") else "unlink"
            if kind == "rmdir" or (kind == "unlinkat" and
                    "AT_REMOVEDIR" in str(row.get("evt.arg.flags", "")).split("|")):
                action = "rmdir"
            paths = [native_path(row.get("fs.path.name"))]
        if any(path is None for path in paths):
            self.gaps[ref] = f"{kind} filesystem path unresolved"
        resolved = sorted({path for path in paths if path is not None})
        if not resolved:
            return None
        record = {"kind": kind, "action": action, "paths": resolved,
                  "actual_mutation": actual, "exit_ref": ref}
        if kind in METADATA:
            record["requested_metadata"] = {
                name: row.get("evt.arg." + name) for name in names
            }
            if kind == "fchownat":
                record["path_resolution_flags"] = row.get("evt.arg.flags")
                self.gaps[ref] = "fchownat native symlink-follow flags unverified"
        self.mutations.append(record)
        return record
