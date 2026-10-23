# Receipt workflow

A native staged repair now passes twelve authored local parser checks. This is
bounded functional verification, not live-agent injection resistance, generated
attack coverage, Skill Lift or an activation path.

The contract was frozen before repair in
`results/integration/receipt-contract-71f5e2f2/manifest.json` (SHA-256
`8a35b9ffcfdb3749df78ad5889bd3ff91ccad669dcd10f5ada900d5207582e81`).
Four development cases cover ordinary extraction, hostile receipt text,
contradictory totals and missing fields. Eight unseen cases cover role text,
Markdown overrides, bidirectional text, shell text, file references, matching
duplicates, contradictory dates and an empty document. Expected outputs and
input bytes are committed together. These cases are authored fixtures, not
independent attack trials. The engineer can read them; the repair model did not.

The repair conversation received the original generic guide/source and general
parsing requirements. Native Hermes read the guide before producing code. Only
`skill_view` was available during generation; no receipt inputs, unseen case
names, attack text or runtime output were sent to inference. Conversation ended
before local native staging and execution. A sealed release binds the selected
candidate to the frozen contract and refuses subsequent repair against that set.
Source is not manually corrected after generation.

Selected preparation: `results/integration/local-parser-8fc64684/preparation.json`.
Model: `nvidia/nemotron-3-super-120b-a12b`, selected from the actual account catalog.
Candidate SHA-256:
`7d74003d712e3d30c34c9389cbd6ed41c28bf387b695bd8b66d821fa9d47f3bc`.
Parser SHA-256:
`2d64af3f68ea7cfdc6255600fed2b5fdb963c6e36f4414cb379f0cf41e902271`.
Complete native Tier 1 passed. Native pending ID `1b83636a` remains inactive.

Native SkillEvaluator generates its keyless full template and BYOT scaffold;
native Harbor owns Linux Docker execution, collection and cleanup. The authored
JSON oracle checks domain correctness. Source, collected inputs and rewards are
hash checked and recomputed before the persistent review records each split.
Both development and unseen splits must pass for combined functional success;
a recorded failure cannot be erased by a later pass of the same split. E10 exposes
only case outcomes and identities, not receipt values. This adds no replacement
generator, harness, collector or enforcer.

First combined run `receipt-workflow-1d9ca868` verified all four comparisons:
repaired development 4/4 and unseen 8/8; original development 0/4 and unseen 0/8.
The run then failed before OpenShell candidate execution because its workload
name exceeded the native nineteen-character limit. The limit now has an offline
regression. The retry stalled on VM startup before evaluation; no new functional
result is inferred from that failure. Historical failures stay archived.

```sh
make receipt-workflow
# Optional metadata-only review, within the aggregate $0.75 trial limit:
.venv/bin/python -m scripts.receipt_workflow --explain
```

Requires the existing local `sgtrace-clean` VM, native gateway, pinned dependencies
and selected preparation. No receipt values or provider credentials are forwarded
to the VM. The generated policy is a draft; it is not enforcement proof for this
candidate. Native runtime comparison uses an empty interpreter control, not the
original parser as a runtime predecessor. Original-versus-repaired functionality
is compared in Harbor. Broader native evidence, new-candidate enforcement,
live-agent evaluation, safe activation and installed rollback remain open.

Current blocker: three native boot recovery approaches produced no console/SSH.
A final bounded workflow failure (`receipt-workflow-cfbc6f55`) saved the report,
preserved pending/source identities and read back both retained machines Stopped.
The original native firmware was restored; the VM disk remains intact. Capture
and fresh-candidate enforcement have not run. File-only draft compilation now
passes; process/tool allowlists remain explicitly unsupported. After automatic approval
review required explicit consent, the user approved the prepared metadata export
to Nebius. One Nemotron Super call completed and recommended hold for incomplete
independent replay. No receipt values, code, credentials or unseen attack text
were sent. Nine preparation calls plus one review cost an estimated $0.00756984
at configured reference rates, not a billing measurement. Final
`make test`: 290 passed, Ruff clean.

Recovery supersedes the earlier startup blocker: the same pinned image passed
multiple fresh boots, including after provisioning. Original disk and diagnostic
clone are preserved; native Lima promoted the healthy replacement. Compose 5.6.0
is now explicitly pinned in fresh setup. Final `receipt-workflow-c9ef9c98` exits
0, repeats the exact four group outcomes and records native repaired execution
`kernel-7c2e5480` with correct receipt output and native read/write references.
43,269 events are scoped to the container; complete tracing remains false.
All four retained machines read back Stopped. File policy remains a draft until
this candidate's fresh enforcement check; the pre-capture advice is correctly
stale after new evidence. No second model call has been made.

The actual repaired resource now has same-image native file enforcement proof
(`receipt-policy-e362441b`). Both UID-1000 sandboxes execute its real file-argument
CLI and produce the correct receipt output. The fake private file has mode 0644
in both; permissive read succeeds, restricted read returns EACCES/13. Native
Docker readback identifies the same image, its saved image archive has a recorded
SHA, parser hashes match before/after and native policy equals the current draft.
The existing review verifier persists both raw outcomes and policy; this proves
one file canary, not general network/process enforcement or complete tracing.

First canary run `f8663ee9` used the wrong adapter calling convention; functionality
failed despite the private denial. It was rejected and preserved, never counted
as success. Only the adapter was corrected; the released repaired source stayed
unchanged. `make receipt-workflow` now includes this native file trial. Earlier
pre-capture model advice remains explicitly stale; no extra call is made unless
requested. Final offline suite: 292 passed, Ruff clean.

Final integrated verification: `make receipt-workflow` exits 0 at
`receipt-workflow-5ec68b4a`, including `kernel-37054f69` and
`receipt-policy-d0e34b44`. Twelve repaired checks pass, twelve original checks
fail, native execution is correct, and the exact file-policy canary passes.
Capture has 42,521 scoped events and reported driver drops 0; loss/completeness
is not established. All four Linux machines are Stopped, pending/source hashes
are preserved, active skill is absent and decision remains held. Final tests
292 passed/Ruff clean; current state saved in `../outputs/skillguard-core-verification.json`.

The workflow now also runs a separately labeled native metadata diagnostic.
This **verifies a policy limitation**, not metadata protection. In two fresh
UID-1000 containers from the same image, a fake file starts owned by UID 1000,
GID 0, mode 0640. Read/write control permits its byte write; read-only policy
denies that write with EACCES/13. Both still permit mode 0600 and GID 1000.
Raw policy/image/outcomes are bound and persisted as E11; the existing E5
private-read denial proof stays separate. The decision explicitly holds for
missing permission/ownership denial. Candidate code does not execute in this
diagnostic, and no replacement enforcement or relaxed native controls are used.

This matches the [kernel's documented Landlock limitations](https://docs.kernel.org/userspace-api/landlock.html).
Ownership, immutable images or supported read-only mounts need separate
verification before relying on a narrower task profile; a path rule alone
cannot establish metadata protection for agent-owned files.

The follow-up `metadata-policy-5087bf39` adds a **separate root-owned control**
to the same native diagnostic. The fake file starts UID/GID 0, mode 0444,
under a root-owned 0755 parent. Both fresh containers run effective UID/GID
1000 with native `/proc/self/status` reporting zero effective capabilities.
Both can read the fake file, but byte writes return EACCES/13, chmod and group
changes return EPERM/1; owner, group, mode and content remain unchanged. This
holds even with the explicit read/write grant in the permissive control.
The original agent-owned file still permits chmod/group changes. E11 records
both facts, without resolving the general native policy gap or authorizing
activation. This control verifies neither path replacement, mount immutability,
privilege transitions nor the candidate's execution. Existing source image
ownership remains unchanged. Historical gap records without this optional
control remain readable; no missing control is inferred as a passing result.

Final `make receipt-workflow` exits 0 at `receipt-workflow-da61f2fa`:
repaired 4/4+8/8 and original 0/4+0/8, passing native capture `kernel-b3280e8d`,
successful private-read denial `receipt-policy-0b04065b`, and confirmed metadata
gap `metadata-policy-70dbe7f7`. Exit 0 means the declared checks/diagnostic ran,
not that protection or activation passed. Review held, all four Linux machines
Stopped, pending/source unchanged, active absent. `make test`: 336 passed,
Ruff clean. No model requests; generated-case export approval remains pending.

The subsequent explicit approval permitted one model-generation call only.
`generated-receipt-eval-5b1574d3` used it: HTTP success but token-limit truncation
and native dataset parsing failure. No generated suite or agent result exists.
E12 records that failure separately; earlier passing authored cases are unchanged.
Exact request authorization is consumed across command invocations. Revised
offline proposal `generated-eval-preview-30a0a5a8` disables thinking through
native SDK options, without changing exported guide/guidance, model or output
bound. It has not been sent; a further call needs fresh explicit authorization.
Current offline verification: 369 tests pass, Ruff clean, candidate held/inactive.

The separately authorized corrected call succeeded on 2026-10-04:
`generated-receipt-eval-2e919fe9` produces four cases, finish `stop`, 873 output
tokens and zero reported reasoning tokens, estimated $0.000267. Offline
`scripts.review_generated_receipt_evaluation` reproduces the exact native
request/response/dataset and uses native starter-task scaffolding/schema/contract
validation. No new inference or task execution. Current E12 records dataset
production with executed cases 0; prior failure retained in history.
The generated questions contain no injection attack prompts and the scaffolds
retain placeholder domain instructions/grading. Native structure validation
does not make them valid receipt/adversarial evaluations. Candidate stays held.

Metadata diagnostic now also attempts content/metadata changes, unlink and
rename on the exact selected parser. `metadata-policy-a94658a8` verifies all
denials and unchanged source SHA/UID/GID/mode under current native source rules,
with root-owned 0444 parser and 0555 parent directories at effective UID 1000
and zero capabilities. This is bounded source protection in a diagnostic image,
not candidate replay or all-image/privilege-transition protection. Agent-owned
file metadata still changes; broader hold remains. `make test`: 396 passed,
Ruff clean; all machines stopped and pending/source unchanged.

The workflow now verifies six native fake Unix-socket/pipe transfers and preserves
the unsuccessful localhost UDP attempt separately. Socket/IPC byte observations
appear in E9's process comparison; they do not imply resolved peers, delivery,
ancillary-data coverage or FD lifetime reconstruction. Failed control validation
stops the combined workflow. These are native tracing controls, not AI-agent
resistance or completed live evaluation. No additional inference is needed.

File identity analysis is now optional in the generic process comparator and
enabled by the native workflow with six source-bound live-handle controls. E9
keeps device/inode observations alongside reported descriptor paths; hardlinks,
rename/replacement and reused descriptor numbers do not collapse path rules.
Fixed controls prove their particular known operations only. Generic alias,
mount/inode-generation and descriptor lifetime coverage stays incomplete.
