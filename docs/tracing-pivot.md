# Tracing architecture decision

SkillGuard can stage and reject real learned skills, preserve review evidence,
run controlled work in OpenShell, and draft file policies. It cannot yet collect
trustworthy, complete behavior for arbitrary candidate programs. Gate 2 is open;
automatic activation must remain unavailable.

Update 2026-10-02: the fresh Linux runner and independent Sysdig modern-BPF fixed
integration probe passed (`kernel-bfba4535`). File read/write, child exec, localhost
attempt and a CLONE_UNTRACED child write are captured outside unchanged workload
controls. Native driver drops 0; workload and VM stopped. The adapter retains
unresolved records and complete=false. The storage blocker is resolved; full
arbitrary-candidate evidence, startup, failure protocol and byte binding remain
unverified. Gate 2's full skill-execution requirement is still open.

## Evidence already obtained

| Approach | Actual result | Why it does not pass the gate |
| --- | --- | --- |
| Python audit inside the VM | Controlled file/network/process fixtures captured | The candidate shares the observer's process and can evade it |
| Native tracing inside the workload | ptrace returned EPERM; pinned seccomp also denies BPF | Enabling either for candidate-controlled code would weaken isolation |
| Native OpenShell event export | Logs captured from live VMs | No successful-file-read class; the SSH trial emitted no Python launch event |

Latest terminal integration: `results/integration/ssh-backend-15305c6b`.
Both native SSH execute and terminal_tool completed a fake receipt task as Linux
UID 1000, without profile sync or checked provider credentials. Native stopped
readback confirms cleanup. This proves connectivity and bounded execution, not
complete tracing, arbitrary-skill safety or Skill Lift.

## Approved investigation direction

User approved this direction on 2026-10-01 with "cool. go aheah". This authorizes
the investigation; it does not establish tracing coverage or approve candidate
activation.

Investigate a Linux runner with an existing system tracing tool operating outside
the candidate's privilege boundary. Keep candidate ptrace/BPF restrictions, use
fake data, retain OpenShell enforcement, and continue using the upstream evaluator
harness. SkillGuard should only adapt existing evidence into its envelope; it
should not build a monitoring service or a replacement evaluation harness.

Start locally to preserve credits. A Linux VM alone is insufficient: the existing
collector must demonstrably observe the actual restricted workload from a trusted
boundary. Before changing the execution architecture, prove file read/write,
child execution and localhost network coverage, observer isolation, event loss
detection, exit cleanup and binding to candidate bytes. If no existing supported
arrangement satisfies those checks, report the incompatibility instead of relaxing
the evidence gate. The initial Colima VM failed image decompression with insufficient
host disk space. The smaller native Lima retry booted Debian, installed the pinned
OpenShell and strace, and reached Ready on the Docker backend after replacing
Docker 26.1.5 with official 29.8.2. This resolves boot/connectivity discovery.
Before attachment, host storage again fell below 400 MiB and the guest shell
reported I/O errors. The VM is now Stopped; no independent trace was captured.
Fresh setup guards are 10 GiB for Colima and 8 GiB for Lima, raised after the actual
4-GiB-margin failure. Cleanup of the failed outside-repo image awaits authorization.

`scripts/linux_trace_probe_guest.py` is an unexecuted fixed integration experiment
for an existing Ready test workload. It saves root-owned artifacts outside the
workload, checks native process identity and attachment, and includes a harmless
CLONE_UNTRACED child marker. Upstream strace documents that such children can escape
`-f`; `--kill-on-exit` is incompatible with `--attach`. The pinned OpenShell seccomp
source rejects clone with CLONE_NEWUSER, but has no CLONE_UNTRACED rejection rule.
These are unresolved coverage/failure limits, not reasons to relax candidate controls.
Reference: [strace manual](https://man7.org/linux/man-pages/man1/strace.1.html).

The other available direction is to narrow the product to controlled procedure
reviews and file-policy demonstrations, explicitly dropping arbitrary-code
behavioral proof and automatic approval. That changes the original mission.

AGENTS.md requires: "If gate 1 or 2 fails after real effort, stop and report. That
is a pivot decision for the human." The architecture direction is now authorized;
an unverified Linux setup remains insufficient to pass the tracing gate.

### 2026-10-02 bounded failure follow-up

The independent fixed capture is repeatable. In `kernel-583db50c`, the operator
killed the native collector after readiness; the fixed task passed but native
capture failed with absent final statistics and missing markers. Its actual
artifacts held an isolated fixture review across separate CLI processes.
A fresh normal capture then passed (`kernel-4ce2f80e`). Both workloads and the VM
were stopped. This verifies one infrastructure fault and persistence path;
actual candidate binding, startup, broader lifecycle coverage and activation
remain unverified. See [fixed probe and limits](linux-kernel-probe.md).

### Actual known pending derivative, 2026-10-02

Native Hermes read the exact learned guide, produced parser source without seeing
runtime receipt inputs, and staged it through native write approval. Complete
Tier 1 passed. Source-read-only OpenShell execution under Sysdig from before
startup then failed the ordinary receipt functional check (subtotal mistaken
for total). Independent program/input/output references and source/image checks
are archived; automatic review persistence held it (`kernel-f4ab3c1b`). This
moves beyond a hand-written fixed script to one real generated derivative.
Full arbitrary-candidate coverage, candidate-only differential replay and safe
activation remain unverified. No repair or benchmark result is claimed.

### Process attribution follow-up, 2026-10-02

`kernel-73f84880` now separates the known parser and an empty interpreter control
using native process start/parent identities and observed lifetimes. The diff
excludes unrelated operator activity. It is not an installed-version comparison
or Skill Lift baseline. Native capture reported zero drops, but 29 candidate mmap
events remain outside completed-I/O envelope semantics and are explicitly shown
as unresolved. Successful zero-copy/async operations also remain gaps. The real
functional failure and partial evidence keep the candidate held. Full arbitrary
coverage and safe activation remain unverified; the broader native adapter and
upstream evaluation integration remain core work.

### Mapping/copy follow-up, 2026-10-02

`kernel-a6a28924` verifies initial mapped permissions and completed native file
copies through reused Sysdig metadata. Shared/private fake-map outcomes and
sendfile/copy_file_range/pipe-assisted splice checks passed. Existing native
controls deny the three tested io_uring calls; no I/O was submitted. Those narrow
semantics are now represented, but they do not establish page access, mapping
lifetimes/permission changes, alias/race handling, general pipe/socket flow, or
arbitrary process completeness. Zero parser mapping gaps is not full Gate 2.
Same actual functional bug still holds the staged derivative; activation remains
unavailable. This remains the approved external-collector direction, with no new
SkillGuard collector, enforcement service or replacement evaluator harness.
