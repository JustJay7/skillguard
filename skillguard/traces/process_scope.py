"""Attribute bounded native events to a known parser and an empty control.

This adapts existing Sysdig metadata, never collects or enforces. Native PID plus
process start timestamp distinguishes PID reuse. Process exit is a window bound,
not proof that every syscall was captured. Supplied JSON remains operator-owned.
"""

from __future__ import annotations

import json

from skillguard.envelope.diff import diff_envelopes
from skillguard.envelope.schema import BehavioralEnvelope
from skillguard.traces.file_identity import analyze_file_identity
from skillguard.traces.mapping_regions import analyze_mapping_regions
from skillguard.traces.sysdig import SYSDIG_FORMAT, parse_sysdig

PROCESS_FORMAT = SYSDIG_FORMAT + " %proc.ppid.ts %proc.args[0]"
PARSER = "/opt/skillguard-candidate/scripts/parse_receipt.py"
CONTROL = "/opt/skillguard-baseline.py"
LAUNCHER = "/opt/skillguard-launch.py"
PYTHON = "/usr/local/bin/python3.12"


def _identity(row: dict, parent: bool = False) -> tuple[int, int]:
    prefix = "proc.ppid" if parent else "proc.pid"
    values = (row.get(prefix), row.get(prefix + ".ts"))
    if any(type(value) is not int or value <= 0 for value in values):
        raise ValueError("Native process start identity missing or invalid")
    return values


def compare_parser_to_control(text: str, *, container_id: str,
                              page_size: int | None = None,
                              include_file_identity: bool = False) -> dict:
    """Compare this known derivative with an actual empty-interpreter control.

    Not an old executable version, agent evaluation, or absence/safety proof.
    Only descendants connected by native parent PID AND parent start timestamp
    are included. Missing root/descendant lifetime or ambiguous roots fail closed.
    """
    parse_sysdig(text, container_id=container_id)  # full binding/duplicate checks
    if type(include_file_identity) is not bool:
        raise ValueError('File identity inclusion must be explicit boolean')
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    rows = sorted((r for r in rows if r.get("container.full_id") == container_id
                   and r.get('container.id') == container_id[:12]),
                  key=lambda r: r["evt.num"])

    def root(script: str) -> dict:
        matches = [r for r in rows if r.get("evt.type") in {"execve", "execveat"}
                   and r.get("evt.dir") == "<" and r.get("evt.rawres") == 0
                   and r.get("proc.exepath") == PYTHON and r.get("proc.args[0]") == script]
        if len(matches) != 1:
            raise ValueError("Expected unique native executable start: " + script)
        _identity(matches[0])
        return matches[0]

    control, candidate, launcher = root(CONTROL), root(PARSER), root(LAUNCHER)
    if (not launcher["evt.num"] < control["evt.num"] < candidate["evt.num"]
            or _identity(control, True) != _identity(launcher)
            or _identity(candidate, True) != _identity(launcher)):
        raise ValueError("Control and candidate require the same observed native launcher")

    def scope(start: dict) -> dict:
        starts = {_identity(start): start["evt.num"]}
        ends = {}
        for r in rows:
            try:
                key = _identity(r)
            except ValueError:
                continue
            if r.get("evt.type") == "procexit" and r.get("thread.tid") == key[0]:
                if key in ends:
                    raise ValueError("Duplicate native process exit identity")
                ends[key] = r["evt.num"]
        # A child's first observed event must have a native parent still inside
        # the selected execution. Reparenting later never erases that association.
        first = {}
        for r in rows:
            try:
                key = _identity(r)
            except ValueError:
                continue
            first.setdefault(key, r)
        changed = True
        while changed:
            changed = False
            for key, r in first.items():
                if key in starts:
                    continue
                try:
                    parent = _identity(r, True)
                except ValueError:
                    continue
                if (parent in starts and starts[parent] < r["evt.num"]
                        <= ends.get(parent, float("inf"))):
                    starts[key] = r["evt.num"]
                    changed = True
        if any(key not in ends or ends[key] <= begin for key, begin in starts.items()):
            raise ValueError("Native process lifetime missing or invalid")
        selected = []
        for r in rows:
            try:
                key = _identity(r)
            except ValueError:
                if r.get("proc.pid") in {k[0] for k in starts}:
                    raise ValueError("Selected activity lacks native start identity") from None
                continue
            if key not in starts or r["evt.num"] < starts[key]:
                continue
            if r["evt.num"] > ends[key]:
                raise ValueError("Native activity exceeds selected process lifetime")
            selected.append(r)
        selected_text = "\n".join(json.dumps(r) for r in selected)
        evidence = parse_sysdig(selected_text, container_id=container_id)
        regions = None
        if page_size is not None:
            regions = analyze_mapping_regions(selected_text, container_id=container_id,
                                              page_size=page_size)
            for change in regions['changes']:
                # Remove only the exact old lifetime gap resolved by paired ranges.
                ref = change['exit_ref']
                if evidence.unresolved_events.get(ref, '').endswith(
                        'backing ranges/lifetimes not reconstructed'):
                    evidence.unresolved_events.pop(ref)
            evidence.unresolved_events.update(regions['unresolved_events'])
        file_identity = None
        if include_file_identity:
            file_identity = analyze_file_identity(selected_text, container_id=container_id)
            for ref, detail in file_identity['unresolved_events'].items():
                previous = evidence.unresolved_events.get(ref)
                evidence.unresolved_events[ref] = previous + '; ' + detail if previous else detail
        return {
            "envelope": evidence.envelope, "event_references": evidence.event_refs,
            "mapping_capabilities": (BehavioralEnvelope.from_dict(regions['mapping_capabilities'])
                                     if regions else evidence.mapping_capabilities),
            "mapping_region_analysis": regions,
            "memory_mappings": evidence.memory_mappings,
            "mapping_changes": evidence.mapping_changes,
            "anonymous_mappings": evidence.anonymous_mappings,
            "file_transfers": evidence.file_transfers,
            "file_mutations": evidence.file_mutations,
            "directory_opens": evidence.directory_opens,
            "socket_io": evidence.socket_io,
            "file_identity_analysis": file_identity,
            "path_mutation_capabilities": evidence.path_mutation_capabilities,
            "unresolved_events": evidence.unresolved_events,
            "scoped_events": evidence.scoped_events,
            "processes": [list(key) for key in sorted(starts)],
            "exec_ref": f"sysdig:{start['evt.num']}",
            "exit_refs": [f"sysdig:{ends[key]}" for key in sorted(starts)],
        }

    before, after = scope(control), scope(candidate)
    if set(map(tuple, before["processes"])) & set(map(tuple, after["processes"])):
        raise ValueError("Native control/candidate process scopes overlap")
    result = {
        "baseline_kind": "empty_python_control", "complete": False,
        "mapping_region_page_size": page_size,
        "file_identity_included": include_file_identity,
        "scope": "Known parser/observed descendants vs empty Python control; partial native I/O",
        "before": before["envelope"].to_dict(), "after": after["envelope"].to_dict(),
        "diff": diff_envelopes(before["envelope"], after["envelope"]).to_dict(),
        "mapping_capabilities_diff": diff_envelopes(
            before["mapping_capabilities"], after["mapping_capabilities"]).to_dict(),
        "path_mutation_capabilities_diff": diff_envelopes(
            before["path_mutation_capabilities"], after["path_mutation_capabilities"]).to_dict(),
        **{prefix + "_" + key: value for prefix, data in (("before", before), ("after", after))
           for key, value in data.items() if key not in {
               "envelope", "mapping_capabilities", "path_mutation_capabilities"}},
        "before_mapping_capabilities": before["mapping_capabilities"].to_dict(),
        "after_mapping_capabilities": after["mapping_capabilities"].to_dict(),
        "limitations": [
            "Control has no skill logic; not an installed old version or Skill Lift baseline",
            "Native metadata is operator-supplied, not authenticated telemetry",
            "Only observed descendants; missing ancestry and unobserved operations remain gaps",
            "Mapping capabilities are separate from completed byte I/O; page access unobserved",
            "Ranges require native page size; missing lifetimes and remaps remain gaps",
            "Native path mutations do not canonicalize aliases or reconstruct inode lifetimes",
            "Reported device/inode matches do not prove aliases, FD generations or current paths",
            "Socket/IPC byte counts retained; peers, FD sharing and ancillary data remain partial",
            "Zero-copy/async and other operations remain incomplete; not every syscall",
            "Interpreter/cache differences may appear; no absence or activation proof",
        ],
    }
    return result
