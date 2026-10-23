# Fixed Linux capture verification

Run from the SkillGuard checkout on this Mac. This uses existing Lima, OpenShell,
Sysdig modern BPF and strace with fake data only. It cannot evaluate arbitrary
skills, grant complete evidence, run Skill Lift or approve activation.

The damaged `sgtrace` instance is preserved Stopped. Use the fresh `sgtrace-clean`
instance. No host directories, SSH agents, provider keys or Hermes profiles are
mounted/forwarded. Guest root owns the observer; workload remains UID 1000.

```sh
env LIMA_HOME=/Users/jay/Documents/Codex/2026-09-29/can/work/lr \
  limactl start --yes --name sgtrace-clean --timeout 8m config/linux-trace.yaml

env LIMA_HOME=/Users/jay/Documents/Codex/2026-09-29/can/work/lr \
  limactl shell --workdir /tmp sgtrace-clean -- sudo sh -s -- sg-linux-trace-demo \
  < scripts/linux_probe_setup_guest.sh

.venv/bin/python -m scripts.linux_kernel_probe --sandbox sg-linux-trace-demo
```

Use a new dedicated workload name for each run; native OpenShell limits names to
19 characters. The collector package must be present at `/opt/skillguard-sysdig`;
fresh configuration extracts the checksum-pinned upstream package, without DKMS
or postinstall. The actual retained clean instance has that exact package already.
Lima start reuses existing instance configuration; it does not apply subsequent
YAML changes to an existing VM. Fresh config validates; earlier manual installation
and extraction of the same pinned tools were executed in the clean instance.

Native gateway readiness is checked before create. The kernel probe waits for
native JSON output identifying the exact container before executing the fixed
task. Native systemd bounds the collector to 120 seconds; the -M duration option
was unreliable in actual trials. Metadata format retains missing optional fields;
display filtering preserves native state. No buffer/argument fields are saved.

Outputs stay private under `results/integration/kernel-*`; the latest summary is
`results/kernel-backend-latest.json`. Each run saves metadata, statistics, immutable
hashes, fixed probe bytes, policy/container readback, event references and envelope.
It checks completed receipt I/O, normal child execution, localhost attempt and a
harmless CLONE_UNTRACED child write. Workload and runner are stopped afterward and
native readback verifies cleanup.

Latest executed run: `kernel-bfba4535`, fixed probe passed, native driver drops 0,
18,945 bound scoped events. `sysdig:134186` records the escaped child's 26-byte fake
write that strace missed. Full candidate replay and startup/failure guarantees are
not established. Unsupported teardown records and an unresolved mediated connect
remain explicit gaps. `complete=false`, `activation_eligible=false` always remain
on these integration artifacts. Missing statistics, ambiguous identity on actual
completed operations, malformed events or missing coverage markers fail the probe.

## Bounded collector-loss verification

With a fresh fixed workload Ready, run:

```sh
.venv/bin/python -m scripts.linux_kernel_probe --sandbox sg-linux-trace-f1 --simulate-collector-loss
```

The operator kills only this experiment's transient Sysdig service with native
`systemctl kill --signal=SIGKILL`, after native output readiness and before the
fixed task. Native readback must confirm `ExecMainCode=2`, `ExecMainStatus=9`,
`Result=signal` and a non-active collector. The task still runs unchanged.
Exit 0 in this mode means the expected fault was verified and the VM stopped;
`fixed_probe_passed=false` remains explicit. It does not mean the capture passed.

Executed run `kernel-583db50c`: collector `failed`, final statistics absent,
coverage markers missing, functional receipt check passed. Raw capture, empty
native statistics, native signal state and task output are retained and hashed.
The false completeness/activation fields remain unchanged.

Attach this bounded report to an existing review using:

```sh
.venv/bin/python -m skillguard.cli capture-probe REVIEW_ID --store REVIEW_STORE --report results/integration/kernel-583db50c/backend.json
.venv/bin/python -m skillguard.cli decide REVIEW_ID --store REVIEW_STORE
```

`capture-probe` archives the manifest's local files and checks their hashes. It
records infrastructure health separately from `replay`, with
`candidate_executed=false`. It cannot grant independent or complete candidate
replay, even for a healthy fixed capture. Negative native health checks add
explicit review hold reasons. Archive corruption refuses a decision, and an
updated probe changes the evidence revision used by model advice.

The executed persistence check used an isolated synthetic pending fixture and
three separate CLI processes. Its decision remained `held`, with
`activation_permitted=false` and all three capture failure reasons retained.
Raw result: `results/integration/kernel-583db50c/review-verification.json`.
This verifies the bounded infrastructure fault and persistence path; it does
not execute the learned candidate, prove every failure timing, stop arbitrary
candidate activity automatically, or finish Phase 0 Gate 2.

Recovery was executed on fresh workload `sg-linux-trace-f2`, run
`kernel-4ce2f80e`: fixed capture passed, collector active through the task,
22,657 bound scoped events, native drops 0. Escaped-child write reference
`sysdig:145362`. Workload and VM stopped. No persistent collector repair or
candidate security restriction change was needed.

## Capture before fixed-workload creation

Run guest setup with a second argument `prepare-only`, then:

```sh
.venv/bin/python -m scripts.linux_kernel_probe --sandbox sg-linux-trace-s2 --capture-startup
```

The named workload must be absent. This mode reuses Sysdig `-w` native capture
files; a native `-r` reader finds an actual root ready-marker write before native
OpenShell creation. The workload's first Python invocation writes a fake startup
marker. After stopping capture, Sysdig decodes only exact-container events with
display filtering. The binary recording is private and can contain one-byte I/O
buffers and process metadata. It is restricted to the isolated fake-data VM.

`kernel-22a69e1b` passed: startup reference `sysdig:174648`, reported driver drops
0. Earlier all-guest streaming JSON trial `kernel-ee085ac1` dropped 93,912 events
and failed. Unknown native runc FD roots stay unresolved; the parser does not
invent paths or grant completeness. No actual learned candidate ran in these
fixed startup trials.

## One known pending learned derivative

After `.venv/bin/python -m scripts.hermes_local_parser_probe` prepares a validated
native pending parser, use `prepare-only` guest setup and:

```sh
.venv/bin/python -m scripts.linux_kernel_probe --sandbox sg-linux-trace-p2 --capture-startup --prepared-parser results/integration/local-parser-0a9ae65b/preparation.json
```

This accepts only the known parent guide and its archived two-file derivative,
with unchanged review/source hashes and complete native Tier 1 checks. The model
is finished before one fictional receipt enters the image. Existing native
Docker/OpenShell builds a root-owned read-only source image; the fixed launcher
executes the derived parser. Independent Sysdig records from before creation.
The wrapper archives bounded native outcome evidence and holds the review. Exit
0 means capture and persistence succeeded, **not** that the learned skill passed.
Check `candidate_execution.functional_passed` and `review_decision` explicitly.

Actual initial execution `kernel-315da7ff` passed capture but failed functionality:
the parser confused subtotal with total. It remains inactive. Source/image
association and kernel I/O refs corroborate this known test; workload-written
reports alone do not authenticate arbitrary execution. Combined probe activity
must not be used as a candidate-only diff or a Skill Lift benchmark.

The automatic capture-to-review path was executed on `sg-linux-trace-p3`, run
`kernel-f4ab3c1b`: wrapper exit 0, automatic archival confirmed, capture passed,
40,631 bound events, reported drops 0, functional check failed and review held.
Model advice was refreshed against those new references and still recommended
hold. `candidate-review-final.json` preserves the final review and pending/active
checks; original learned guide remained unchanged.

## Known parser process tree vs an empty Python control

Add `--compare-control` to the known prepared-parser command. The immutable image
contains a root-owned `pass` script; the launcher runs it before the unchanged
candidate. Native `proc.args[0]` identifies the expected script at successful exec,
and `(proc.pid, proc.pid.ts)` identifies its lifetime. Native `proc.ppid.ts` ties
both roots to the observed launcher and any observed children to the selected
tree. Main-thread native exit is required; missing/ambiguous roots, missing exits,
PID reuse, overlapping scopes and altered artifacts cannot yield an accepted diff.
Command argument buffers, environment and I/O payloads are not exported in this
JSON format; only the first argument (script path for these roots) is added. The
private native capture still contains one-byte buffers/process metadata.

`kernel-73f84880` verified this path: 658 control and 1,671 parser events, zero
reported driver drops, same failed total check, persistent held review and stopped
workload/runner. Parser input read is `sysdig:208192`, output write `sysdig:208208`.
The raw diff has 20 added read paths (source/input and imports), one output write,
and removal of the control's script read. It uses the existing behavioral envelope
and diff; it does not subtract an invented list of runtime paths.

This is an **empty Python control**, not an installed old skill or Skill Lift
measurement. Native metadata is still operator-supplied and unauthenticated.
Observed ancestry is bounded; incomplete ancestry is not proof that every child
was accounted for. The parser's 29 and control's 23 successful mmap events remain
explicit unresolved access references. Sysdig's native mmap entry can resolve an
FD, but its exit lacks that parameter; this adapter does not pair mappings or
infer actual page accesses. Successful zero-copy I/O and io_uring operations are
also marked unresolved. No absence, complete coverage or activation is granted.

The review recomputes this diff from hash-checked latest native artifacts; E9
includes its exact control type, lifetime references and gaps. Later executions
invalidate the comparison, and changes to model-visible evidence stale older
advice. This trial makes no model call; stale advice is preserved as historical.

## Mapped capabilities and native completed copies

The current formatter also exports native mapping FD/protection/flags and
sendfile/splice/copy_file_range descriptor arguments. Entries and completions
are paired by host PID, native process start timestamp and host thread ID;
thread exit clears pending calls. Repeated/nested entries, absent completions,
bad order or identities, and unsupported descriptors stay explicit gaps.

Mapping permissions appear in `memory-mappings.json` and separate
`mapping_capabilities_diff`, **not** ordinary completed-read/write facts. A
successful anonymous map has no backing file; a private writable map permits
private changes, not a source-file write. Shared writable maps project a possible
file-write capability. `page_access_observed` stays false. Region lifetimes,
mprotect/mremap, architecture-dependent effective permissions, file aliases and
concurrent descriptor changes remain unaccounted for.

Completed copies with positive byte counts add file read/write facts to the
existing envelope. Native sendfile has both FDs on entry; copy_file_range has its
input FD on entry and output FD on completion; splice exposes both on entry.
Resolved regular-file endpoints become facts independently. Pipe/socket peers
remain unresolved, even if a known file endpoint is observed. No general dataflow
or network absence proof is produced. Raw transfer details are in
`file-transfers.json`; the fixed marker assertions are archived in the backend.

Final run `kernel-a6a28924` passed all known fake mapping and copy checks:
read-only mapping `sysdig:338775/338776`; private writable copy
`sysdig:339035/339036`; shared writable map `sysdig:339550/339551`;
16-byte sendfile `sysdig:340367/340368`; 16-byte copy_file_range
`sysdig:340979/340980`; splice file-to-pipe `sysdig:341534/341535` and
pipe-to-file `sysdig:341558/341559`. The known probe checked private source
unchanged and shared source changed; kernel mappings prove initial permissions,
not arbitrary page writes. Splice's pipe endpoints still produce explicit gaps.

The same run tested harmless io_uring entry points, without submitting I/O.
Setup with zeroed parameters and enter/register with an invalid FD all returned
EPERM under existing combined native controls. Independent completion refs are
`sysdig:345485`, `sysdig:345508`, `sysdig:345531`. These match inspected pinned
OpenShell hardening, but do not identify which composed filter denied the calls.
Successful io_uring in any future runtime would still be an unresolved access gap.
No enforcement rule was added or weakened.

Native capture reported zero drops; known parser still failed functionality and
remained held/inactive. Empty-control and parser scopes have 9/11 file mappings
plus 14/18 anonymous mappings, with no unresolved initial mapping metadata in
those bounded scopes. Complete coverage is still false. E9 exposes the separate
mapping diff and transfers, and the regression fixture contains 17 actual known
fake-data native events with source-capture identity. No inference was requested.

## Native filesystem mutation probe
The fixed fake-data workload now includes exclusive empty-file creation,
open-truncation without byte writes, rename/hardlink/symlink, unlink and directory
creation/removal. Existing-file O_CREAT is kept as possible creation rather than
an actual modification. File mutation records are exported to file-mutations.json;
the bounded candidate comparison and persisted E9 reuse these records and the
separate capability diff. Native path aliases/inode lifetime and all flag/syscall
semantics remain incomplete; complete/activation stay false.

Executed final verification `kernel-8eeedeeb` with `--sandbox sg-linux-trace-m3
--capture-startup --prepared-parser results/integration/local-parser-0a9ae65b/preparation.json
--compare-control`: all known mutation checks passed, reported drops 0, unchanged
candidate held for the same actual total failure, workload/runner stopped. A native
directory TMPFILE flag ambiguity remains an explicit gap; see docs/upstream.md.

## Mapping permission changes cannot disappear from review

Native Sysdig's installed `-L` catalog exposes address/length/protection for
mprotect and address/length for munmap, with actual completion results. It
exposes mremap and pkey_mprotect as generic syscall-ID events without usable
arguments/outcomes. The adapter now pairs mprotect/munmap by native process
start and thread identity. Successful changes are saved in `mapping_changes`
and remain explicit gaps because backing address ranges/lifetimes are not
reconstructed. Denied completed calls add no change. Generic mapping events
remain gaps even when their real outcome might be a denial.

This corrects silent omission, not memory access completeness. Initial mmap
capabilities describe initial permissions only; later changes can make them
incomplete. No page access, new file write or current region permission is
inferred from a permission change. Persistent E9 includes the raw paired change
references; legacy evidence without the new semantics remains readable.

Actual fresh run `kernel-506c4705` passed the new fake-file probe. A shared
4096-byte file mapping started read-only, gained read/write permission, changed
its first byte through memory and was removed. Native references are
`sysdig:348430/348431` and `sysdig:348703/348704`; the later mprotect on the
removed range failed. Parser functionality still passed. Control/parser scopes
retain 16/26 observed mapping changes and 21/40 unresolved events, respectively.
Reported driver drops were zero, without a completeness claim. Candidate
remains held; workload and all four retained Linux machines are Stopped.

The earlier successful `kernel-278fd082` provides the checked-in eight-event
native fixture, including successful mmap/change/removal and denied post-removal
change. Capture/workload/fixture hashes are in the adjacent source metadata.

## Permission and ownership operations

Successful typed chmod/fchmod/fchmodat and chown/lchown/fchown/fchownat now add
the named path to the write envelope without claiming content I/O. Applied mode
or owner arguments are retained verbatim. Descriptor operations use native
file/directory FD identity; missing outcomes, paths or metadata remain gaps.
Generic fchmodat2, truncate/ftruncate/fallocate and other unsupported operations
are still unresolved. These facts do not reconstruct aliases or inode lifetime.

Actual `kernel-41c39fca` supplies five checked-in native events with capture,
workload and fixture hashes. Native mode values are symbolic strings; UID/GID
values are decimal strings. Its external strace shows AT_SYMLINK_NOFOLLOW for
the fake symlink ownership call, while native Sysdig exports flags `0`. Both
fchownat events therefore retain an explicit follow-semantics gap; no binary
root cause or resolved target identity is inferred.

Fresh final standalone `kernel-0ff20d20` and integrated `kernel-b3280e8d` verify
all five fake metadata operations and unchanged content, alongside the passing
known parser. The latter retains 43,733 container events, reported driver drops
zero, pending/source identities preserved and complete=false. Runtime metadata
changes in the fixed operator probe are not attributed to the learned parser.

After reboot the existing transient gateway may need the setup script repeated
with its second argument `prepare-only`, before a startup-capture probe. Verify
native openshell status reports Connected. Use a fresh workload name; keep failed
reports (including c1368af4/5edcb88c) rather than replacing them.
