# Upstream Candidates

Record fixes that belong in Hermes, OpenShell, SkillEvaluator, or Nebius rather than SkillGuard itself.

## 2026-10-23 — native generation trust separation and adversarial coverage

The pinned native `_generate_with_llm` embeds the complete skill body and developer EVAL guidance in one user prompt. In actual security review `7e2abecf`, it returned four routine receipt/factual questions despite explicit private-file, output-poisoning and forged-role guidance. Its native schema validation succeeded, but these were not adversarial probes. Preserve the paid dataset and the original incomplete review; none receives attack-resistance or security-pass credit.

Candidate upstream improvement: a trusted generation system message that treats SKILL.md as untrusted subject matter, plus declared security-fixture coverage validation before execution. The integration still uses the native generator's prompt construction, schema, parser and task staging. It adds a trusted system message and validates required synthetic target/attack markers, identifiers and local-only URLs; this is input-fixture validation, not a runtime scanner or enforcer. Ordinary questions must not silently earn a security pass.

## 2026-09-29 candidates
- Hermes: examine native gate fail-open import/config handling and document terminal-write boundary; no exploit claim without reproduction.
- SkillEvaluator: Hermes Harbor adapter integration belongs upstream where feasible; preserve invocation evidence.

- OpenShell v0.1.2: official macOS installer omitted e2fsprogs; first MicroVM creation failed with mke2fs/mkfs.ext4 missing. Installed e2fsprogs to retry. Candidate packaging/docs improvement; retain runtime evidence before reporting upstream.

- OpenShell v0.1.2 native supervisor hardcodes /var/log for log and OCSF JSONL sinks; unprivileged macOS native supervisor falls back to stderr. Add configurable log directory and preserve structured OCSF in the gateway push stream (currently shorthand-only, best effort). This would improve evidence export but does not by itself create syscall-complete file-read telemetry.

## 2026-10-01 native skill loading boundary
- Hermes `tools/skills_tool.py:573` documents that skill_view defaults to template/inline-shell preprocessing; later code can install `deps` through pm.ensure. A read-only tool name does not imply a pure file read. Candidate reviews need isolated loading or a documented inspection mode that suppresses both execution paths. The current receipt probe pins inspected bytes with neither feature and restricts tool calls before execution.
- SkillEvaluator's pinned agent/environment registry still lacks Hermes and OpenShell. Keep benchmark execution and dataset generation upstream; the fixed native guide-use integration is not a replacement harness or a Skill Lift score.

## 2026-10-01 native terminal connection and telemetry
- Hermes already exposes TerminalEnvironmentProvider, profile-scoped registration and context-local terminal settings. Its built-in SSH builder does not expose SSH config path or `sync_files=False`, but a registered provider can reuse SSHEnvironment with those bounded settings. A fixed terminal_tool integration passed without modifying pinned source. Prefer these existing extension points to a replacement agent harness.
- OpenShell native ssh-config authenticates through gateway-scoped ssh-proxy sessions. Preserve a separate operator-owned config file instead of editing global SSH settings. The test checked its digest before each native SSH command.
- OpenShell's inspected OCSF classes include process and mediated network events but no successful-file-read class. The SSH probe's captured logs contain startup/configuration/network listener events, with no Python process event despite successful execution. Startup NET records are not candidate egress. Shorthand export is best effort; structured export alone cannot fill missing telemetry. Independent tracing remains an architecture blocker.

## 2026-10-01 Colima configuration discovery
- Colima 0.10.3 (`00f6c297e92a82c04a4ab507db0a61435650d7e8`) checks that COLIMA_HOME already exists before honoring it. A new nonexistent override silently falls back to ~/.colima; this was reproduced during the failed VM setup. Its configuration docs could require directory creation explicitly or the implementation could create the requested directory instead. The local wrapper precreates all state directories and explicitly sets LIMA_HOME. [Pinned source](https://github.com/abiosoft/colima/blob/00f6c297e92a82c04a4ab507db0a61435650d7e8/config/files.go#L49).
## Linux tracing investigation candidates, 2026-10-01

- OpenShell v0.1.2 Docker archive-copy compatibility: Config.User `1000:1000` plus
  upload copy_uidgid=true fails on Debian Docker 26.1.5 with a getent error even
  when the account exists. Same prepared workload reaches Ready on official Docker
  29.8.2. Document tested Docker versions or fix compatibility upstream; no local
  driver patch was made.
- Independent syscall evidence export remains absent. An operator-owned strace
  outside the workload may observe controlled calls, but its documented attachment
  and CLONE_UNTRACED limits prevent complete evidence claims. Pinned OpenShell
  seccomp rejects CLONE_NEWUSER, not CLONE_UNTRACED. Any supported capture/failure
  solution belongs upstream; do not implement a SkillGuard monitoring service or
  weaken candidate restrictions. Live escape test still pending storage recovery.

## 2026-10-02 verified tracing integration findings
- Live harmless CLONE_UNTRACED test now confirms the strace gap. Sysdig 0.41.4
  modern BPF captured the escaped child's actual file write outside unchanged
  OpenShell controls. Consider a supported upstream trusted-event export; this
  fixed experiment is not a new SkillGuard monitoring service.
- Sysdig -M duration stopped immediately in two actual tests despite zero drops.
  Pinned `userspace/sysdig/sysdig.cpp` subtracts unsigned event timestamps. Potential
  out-of-order underflow deserves an upstream reproduction; root cause unconfirmed.
  Native service lifetime is the current bounded-probe workaround.
- Sysdig active process/drop counters do not establish capture readiness: measured
  startup lag missed an entire subsecond probe. An explicit readiness surface would
  simplify secure integrations. Current fixed test waits for exact-container native
  output before execution, with all failed trials preserved.
- Document that `-s 0` retains default snaplen, leading `*` retains missing optional
  fields, and -d filtering is necessary to preserve native state before export.
  Completed mediated-denial events can have no destination; container teardown can
  invalidate enrichment. These gaps must prevent complete-evidence claims.

## 2026-10-02 native evaluation readiness and contract checks
- SkillEvaluator strict BYOT validation accepted task.toml environment.network_mode="none" (all statuses ok), but Harbor 0.13.2 Task parsing rejects it before task resolution. Native no-network mode is "no-network". Consider validating the native runtime schema during contract checks; actual failed run native-eval-0a0b9bb3 retained. Local integration now also parses Harbor Task without patching upstream.
- Keyless dataset/scaffold CLI imports require Harbor through the command module. Help works without the extra but execution raises ModuleNotFoundError. Consider lazy imports or an explicit extra-install error. Native Harbor installed rather than replacing these commands.
- Unconstrained Harbor FastAPI/telemetry installation conflicts with existing Semgrep 1.178.0. Recorded compatible constraints restore pip check and complete static scans. Direct native Harbor needs Docker Compose and NVIDIA's existing custom reward normalizer; our adapter reuses both, not a replacement harness.

## Native Sysdig directory/tmpfile flag ambiguity (candidate only)
- Actual Sysdig 0.41.4 run `kernel-8eeedeeb`, event 202286: ordinary Python directory open `/usr/local/lib/python3.12`, fd.type=directory, flags contain O_RDONLY|O_DIRECTORY|O_NONBLOCK|O_CLOEXEC|O_TMPFILE|FD_LOWER_LAYER, evt.is_open_create=true. Thirteen control/candidate directory opens have this ambiguity. Exact metadata/source capture hash retained in tests/fixtures/sysdig-native-directory-open*.
- [Sysdig 0.41.4 build recipe](https://github.com/draios/sysdig/blob/0.41.4/cmake/modules/falcosecurity-libs.cmake) defaults to libraries 0.21.0. [That release's conversion helper](https://github.com/falcosecurity/libs/blob/0.21.0/driver/ppm_flag_helpers.h) checks `flags & O_TMPFILE` rather than full-mask equality. [Linux's definition](https://github.com/torvalds/linux/blob/master/include/uapi/asm-generic/fcntl.h) makes O_TMPFILE a composite containing O_DIRECTORY. This is consistent with the actual symptom; exact binary dependency provenance remains unattested.
- Candidate upstream fix: distinguish the complete TMPFILE mask and add normal-directory/true-unnamed-file regressions. Audit evt.is_open_create and original O_PATH reduction separately. No native source patched or issue submitted; SkillGuard preserves ambiguous events as gaps instead of inferring a write or safety.
- Oct 7 actual controls (`kernel-684be4d4`) confirm a second affected field: true
  O_RDWR|O_TMPFILE returns a regular zero-link file under fstat, while native
  `fd.type` and `<d>` descriptor formatting say directory. Readonly O_DIRECTORY
  also gets false TMPFILE/create flags. Audit descriptor classification as well
  as open/create flag conversion. Both actual events are saved in
  `tests/fixtures/sysdig-native-directory-controls*`. SkillGuard resolves only
  strictly matched readonly opens and preserves writable unnamed-file gaps;
  no native monitor/enforcer fork or upstream issue was published.

## Native mapping outcome coverage
- Installed Sysdig 0.41.4 `-L` reports full mprotect/munmap arguments and completion results, but mremap/pkey_mprotect expose generic syscall IDs only. Catalog capture: `results/integration/mapping-lifecycle-investigation/native-events.txt`.
- Native JSON address fields are hexadecimal strings without a prefix; lengths are decimal strings. Preserve the native representation until address-range semantics are verified. Actual fake-file mprotect and munmap are independently captured in `kernel-506c4705`.
- Candidate upstream work: typed arguments and outcomes for generic mapping events, and documented native mapping lifetime/descriptor association. No native source change or issue submission made. SkillGuard records unresolved gaps rather than guessing a denial or safe region lifetime.

## Native file metadata policy limits
- Native Sysdig 0.41.4 exports typed chmod/chown completion/path/descriptor and mode/owner arguments, but generic truncate/ftruncate/fallocate/fchmodat2 lack usable outcomes. Broader native inode/alias semantics are still needed.
- Actual `kernel-41c39fca` strace records fake symlink fchownat with AT_SYMLINK_NOFOLLOW; Sysdig exports flags `0`. Native metadata fixture/provenance retained. Candidate upstream reproduction: verify flag conversion/export for no-follow ownership changes. No source patch, binary replacement or issue submission made.
- [Kernel documentation](https://docs.kernel.org/userspace-api/landlock.html) explicitly lists chmod/chown among operations Landlock cannot currently restrict. Same-image OpenShell 0.1.2 trial `metadata-policy-70dbe7f7` confirms read-only content denial but permitted mode/group changes on a fake UID-1000-owned file. Candidate documentation improvement: distinguish byte/path rules from metadata control and document immutable/ownership prerequisites. Any additional enforcement belongs in the existing native runtime, not SkillGuard.

- SkillEvaluator native dataset generation hardcodes 2000 output tokens and the installed generic `LLMClient` sends no model-specific reasoning option and does not inspect `finish_reason`. Actual Nebius Lightning call `generated-receipt-eval-5b1574d3` returns `length` with 2000 reported reasoning tokens and no valid JSON; native parsing rejects it with a generic configuration/response diagnostic. Candidate upstream changes: documented provider-specific options, explicit truncation diagnostics and structured-output guidance. [NVIDIA's Lightning guide](https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning.html) recommends disabling thinking for structured output. SkillGuard supplies only that native SDK option in a separately reviewed offline proposal and preserves the native generator/parser. No upstream PR submitted and no corrected live result claimed.

- Follow-up: explicitly authorized `generated-receipt-eval-2e919fe9` confirms the native SDK reasoning toggle against Nebius: four valid cases, 873 output tokens, finish `stop`, reported reasoning tokens 0. Strict native scaffolding/schema validation also passes offline. However, the four-bucket prompt ignores requested adversarial input guidance, its first question omits the explicit skill name, and a partial date has an imprecise oracle. Candidate upstream documentation/evaluation improvements: separate routing starter cases from adversarial input suites, flag omitted requested categories, and clearly distinguish task schema validity from completed domain grading. No replacement scanner/generator or upstream PR created.

## Native descriptor names and current file identity
- Actual `kernel-260ee2b4` verifies that fd.name retains the old source path after
  rename while an open handle still accesses the original inode. Typed native
  device/inode metadata matches the known live fstat control; a replacement at
  the renamed entry has a distinct inode. This is a verified scope limitation
  of using descriptor names as current path bindings, not an asserted native
  runtime defect. Documentation candidate: distinguish descriptor-name caches
  from current pathname/alias and inode-generation tracking. No native source
  patch, replacement collector or upstream publication was made.

## Oct 8: native Harbor / OpenShell bridge
- Harbor's public custom-environment import point is sufficient for a bounded OpenShell adapter. Native mount requests can be dicts rather than model objects; consumers should normalize both. Native Terminus' root-requested tmux version check needlessly complicates strict non-root environments; it can be checked as the sandbox user.
- OpenShell receipt images require an explicit CMD, a writable workdir and PTY access for Harbor's native tmux. Startup currently reports generic supervisor/provisioning failures; clearer identity/workdir and denied-PTY diagnostics would shorten integration. These were reproduced locally; no upstream report/PR has been sent.
- Independent Sysdig telemetry and OpenShell enforcement can coexist around the native Harbor job. The verified diagnostic remains bounded: private-file open EACCES plus metadata/terminal observation, not general file-object, process or network completeness.

- Harbor 0.13.2 `_parse_skill_frontmatter` rejects an opening YAML delimiter with trailing spaces (`--- `), even though the actual SkillEvaluator static run accepted this guide. Native scanning silently omits the skill. Suggest accepting delimiter whitespace or reporting a clear discovery warning. Local compatibility wrapper is source-pinned, scoped to this delimiter and delegates native YAML parsing; no upstream issue or PR has been sent.

- Hermes' pending create route accepts a description that its later native apply rejects at the 60-character new-skill limit. Consider surfacing native authoring validation when staging so an operator does not discover it after expensive evaluation. The bounded core validates through native apply in a disposable profile before offering installation. No upstream report or PR has been sent.

## Oct 22: bounded multi-job custom Skill Lift collection
Native keyless generation emits at most the documented three positive bucket cases (four with an authored negative), so the heldout preparation invokes native single-case generation per authored case and assembles the returned entries with unique authored ID suffixes. The native BYOT strict checker also warns about skill copying when a source Dockerfile copies only receipt input but separately names `/workspace/skills`; input copying therefore occurs in the explicitly checked post-staging adapter. These are author-owned task changes, not a new generator.

The public collector requires one aggregate Harbor job result per condition. Our conservative per-trial budget reservations create separate native jobs. The bounded comparison uses the inspected native `_extract_rewards`, `_condition_execution_summary`, `average_custom_metrics` and `_compute_custom_lift` primitives over those unchanged trial artifacts. No aggregate job result is fabricated. Candidate upstream improvement: expose a supported collection API for multiple individually bounded native jobs per condition. No upstream issue/PR has been sent.
