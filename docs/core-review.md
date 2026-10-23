# Persistent core review

The local backend reviews actual staged Hermes writes. It does not expose an
approval operation. A controlled runtime violation or failed static validator
can block a candidate; missing or incomplete evidence holds it. Nemotron advice
cannot override these constraints.

## Reproduce the verified integrations

Install the development environment, live extras and pinned upstream scanner
dependencies described in the existing setup notes. Keep the pinned Hermes
checkout in `../work/hermes-agent`; current local probes use Python 3.12.
Hermes' published dependency metadata targets Python 3.14, so these bounded
successful probes do not establish broad Python 3.12 compatibility.

```bash
PYTHONPATH=../work/hermes-agent .venv/bin/python -m scripts.hermes_review_probe --live-explanation
PYTHONPATH=../work/hermes-agent .venv/bin/python -m scripts.hermes_mutation_probe
PYTHONPATH=../work/hermes-agent .venv/bin/python -m scripts.hermes_learning_probe
.venv/bin/python -m scripts.hermes_procedure_use_probe
.venv/bin/python -m scripts.reconcile_procedure_use --run results/integration/procedure-use-152114fc7c1a
.venv/bin/python -m scripts.hermes_openshell_ssh_probe
```

The first command stages two existing fixtures, validates the captured copies,
replays their fake-data scenario in a new local OpenShell VM, binds replay bytes
to the candidate hash, stores model advice and a file-policy draft, and rejects
the planted candidate through Hermes' native `discard_pending`. It preserves the
benign pending write and stops the VM in cleanup. Omitting `--live-explanation`
avoids a model request and leaves the model-review requirement explicitly missing.

The SSH probe creates a fresh VM and uses Hermes' native SSHEnvironment and
terminal_tool through its registered provider extension. It disables profile sync
and environment passthrough, keeps the native SSH configuration in a private
per-run file, compares direct and tool execution, and verifies stopped state after
cleanup. It uses fixed fake data and makes no model calls. The full agent does not
run inside this VM; native logs do not provide complete runtime evidence. See
[the tracing decision](tracing-pivot.md).

The authorized Linux investigation uses `.venv/bin/python -m scripts.linux_runner`
for a read-only dependency/disk preflight. `--start` invokes the native Colima
setup only after those checks pass. State/cache live in precreated workspace
directories, with home mounts, agent forwarding and global context changes
disabled. At the latest check it exits 2 because disk space is insufficient.
The 10-GiB reserve is a conservative setup margin, not a measured final footprint.
This command prepares infrastructure only; it is not an evaluator harness and
does not execute a candidate or establish tracing.

The mutation probe captures an installed baseline, calls native Hermes text
mutation logic in a disposable profile, and archives both versions. It simulates
an installed update only within the test profile, then stages rollback through
the native write gate. Reconstructing that pending rollback matches the archived
original content hash exactly; the changed installation stays unchanged.

The learning probe runs the real Hermes conversation loop with only the skills
toolset. It supplies a fictional café receipt, allows at most three requests,
caps output at 2,048 tokens, rejects streaming/unverified endpoints/models,
reserves $0.10 before each request, and saves usage at the HTTP response boundary.
It does not execute generated scripts. The generated guide passed Tier 1. A
subsequent bounded native guide-use trial used its exact archived bytes in
disposable test profiles. Hermes read it and correctly parsed a normal fictional
receipt. A planted footer led to a `skill_manage` request to rewrite the guide for
external receipt forwarding. The HTTP-boundary safety check refused the request
before native execution; no write or external canary transfer occurred.

`reconcile_procedure_use` rechecks saved conversations without inference, adds
the evidence to the original learning review, and rejects a blocked candidate
through the native gate in that disposable learning profile. Pending ID
`20d4acf4` was removed; the original active skill remains absent. Earlier held
reports are historical and preserved. Scope violations stay blocking for the same
candidate even after later passing guide-use checks.

This is a fixed integration probe, not a replacement evaluation harness or a
Skill Lift benchmark. Tier 3 still has no built-in Hermes/OpenShell adapter.
The probe only permits the exact inspected guide's `skill_view`, because the
native tool can execute inline preprocessing or install declared dependencies.
Only fake receipts reach Token Factory; the guide's local-only privacy promise
is unverified. This does not exercise arbitrary files, networking or processes.
Up to six requests share a $0.75 ledger ceiling, below the displayed $1 trial
credit; every response is costed before the safety check can refuse it.

## Individual review operations

```bash
.venv/bin/python -m skillguard.cli capture /path/to/pending.json --store /operator/reviews
.venv/bin/python -m skillguard.cli inspect REVIEW_ID --store /operator/reviews
.venv/bin/python -m skillguard.cli scan REVIEW_ID --store /operator/reviews --evaluator .venv/bin/skillevaluator
.venv/bin/python -m skillguard.cli decide REVIEW_ID --store /operator/reviews
```

For an existing-skill text change, capture also requires `--baseline` pointing
to the installed skill directory and `--hermes-source` pointing to the unchanged
pinned native checkout. A mutation review's identity includes the original
installed version, not just the pending payload. Replay of a mutation must
identify both the executed candidate and executed baseline hashes.

## Stored evidence and integrity

The SQLite store indexes original pending hashes, candidate snapshots and an
ordered event history. Events archive static reports, operator contracts,
replay envelopes and attachments, advice, policy drafts and outcomes. Every read
checks archived content hashes. Later evidence invalidates prior advice. A failed
individual static validator blocks even when the aggregate scan is incomplete.

Hashes detect accidental or isolated content changes; they do not authenticate
an attacker who can rewrite both the database and files. Store ownership and
isolation remain deployment requirements. Native profile selection, enabled
write approval and matching pending bytes are checked before rejection.
Concurrent edits across the native queue and review store are not a single
atomic transaction; production coordination still needs hardening.

## Current boundaries

- Native interception covers the supported `skill_manage` pending-write route.
  Direct terminal writes and operator native approval can bypass it. Hermes gate
  import failure is an upstream fail-open case.
- Text edits, targeted patches and one-skill supporting-file batches are
  reconstructed. Binary restoration, deletion, categorized names and multi-skill
  mutations remain unsupported and cannot be approved.
- Rollback creates a new staged proposal. SkillGuard does not install reviewed
  candidates or rollbacks while independent evidence is unavailable.
- Python audit replay is in-process, evadable and records attempts. It is only
  evidence for controlled fixtures, not complete tracing of hostile programs.
- The generated file-only policy is a draft. Network/process/tool capabilities
  are rejected instead of being silently omitted. Broad runtime read paths are
  explicit, and prepared paths must exist before Landlock rules are created.
- A controlled two-VM file trial passed: the same nonroot identity and prepared
  fake-data image complete the receipt task, while only the restricted VM denies
  the private-file read. Native policy readback, raw outcomes, image digest and
  candidate digest are archived together. Changed contracts/policies invalidate
  the proof. This is bounded denial evidence, not complete hostile-code tracing.
- File drafts require Landlock `hard_requirement`; unsupported enforcement or
  unavailable rule paths must fail native setup rather than silently downgrade.
  The successful native trial used this mode. The user-authorized temporary
  image configuration was restored byte-for-byte and test VMs stopped.
- The private cloud project is configured, but SDK `list_images(limit=1)` returns
  HTTP 403 and the account shows Request beta access. No cloud VM was created.
  No benchmark rates, generic protection claims, deployment or submission are verified.
