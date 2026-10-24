# SkillGuard

Test what an agent's new skill does before allowing it to learn that behavior.

SkillGuard intercepts native Hermes pending skills, runs NVIDIA SkillEvaluator checks and generated security probes against a real agent in Harbor/OpenShell, records behavior, asks Nemotron to review the evidence, previews bounded permissions and gates installation on explicit approval. Rejection, a known repair and version rollback are included. The frozen runtime profile supports receipt skills; receipt extraction is the test workload.

## Inspect the recorded demo

[Open the public SkillGuard walkthrough](https://skillguard-evidence-demo.jaymalhotra.chatgpt.site). This is a read-only replay of the verified fictional security review, including the blocked update, actual agent commands, both model holds and the human-exception rollback. It has no live agent, credential, approval endpoint or private runtime access.

In the [public source](https://github.com/JustJay7/skillguard), run `python3 -m http.server 8769 --bind 127.0.0.1 --directory recorded-demo` to inspect the included replay. On the configured development checkout, `make demo-bundle` builds the portable bundle and `make demo` serves it on port 8769. The archive is `dist/skillguard-demo.zip`. The full native review application remains separate below. [Submission and recording handoff](docs/submission/README.md).

## Actual public backend

[Open the live SkillGuard workspace](https://literate-space-system-45gjq9qjggwfjw7p-8770.app.github.dev/). This protected application runs in a dedicated GitHub Codespace with its own isolated Debian/OpenShell VM. It uses real server-side Nebius credentials and native agent execution. The operator supplies a separate demo access code; no provider key is sent to visitors. The recorded walkthrough above remains separate.

Codespaces uses the account's included development allowance with a $0 paid-usage limit. It stops when idle or allowance is exhausted; this is supervised development hosting, with no always-on production guarantee. [Cloud setup, private configuration and hosting limits](docs/public-backend.md).

## Live connection and spending authorization

The cloud app and the optional local development app use the same guarded core flow. Only one paid-action deployment should run against the authoritative spending ledger at a time. Its connection panel checks the saved `NEBIUS_API_KEY` against the real Token Factory catalog without a paid inference request. Review and installed-agent actions use that server-side key for real model calls. The key is never returned by the status API or passed into the candidate sandbox. Native OpenShell starts on demand and stops after each operation.

The source default is a $0.75 trial cap. A local operator can explicitly authorize a different aggregate cap (at most $50) in the ignored `results/budget-authorization.json`, for example `{"aggregate_cap_usd": 1.00, "authorization": "My explicit project spending limit"}`. This private file is excluded from source releases. New app proposals inherit the authorized cap; previously issued proposals and claims retain their bounds. Costs and unknown holds are never reset. All model/tool content limits and per-trial request ceilings still apply. The app displays the effective cap and accounted usage.

## Run the app

On the configured development machine:

```bash
make review
```

Open [the local workspace](http://127.0.0.1:8768/). A pending skill appears automatically when native Hermes stages it in the app's learning profile. You can also stage a sample or paste a receipt guide/parser. Choose **Review skill security** to run source checks, twelve native regression cases, four generated annotation probes with the actual agent and a Nemotron evidence review. Inspect recorded actions, behavioral changes and permissions. A restricted pass enables **Approve and install** after acknowledgment; failed checks block installation. If all native checks pass but the model holds its verdict, a separate **Install with held-verdict exception** requires a checked warning and a written reason. The installation remains labeled a human exception, not a security pass. **Reject** preserves the review. **Restore previous version** restores a preserved installation.

**Stage unsafe sample** stages a deliberately unsafe fake-private-file reader. Its blocked review exposes **Stage known repair and review it**, which archives the rejected update and stages the exact previously tested V8 repair for a new review. This is an explicit known repair, not autonomous general code repair. All example/test data is fictional. Receipt-agent and local-parser utilities are under diagnostics.

## What approval means

Approval applies only to this app's fixed OpenShell receipt workspace. Each installed version has its own Hermes profile and exact source hash. An atomic pointer selects the active version; rollback preserves both copies. Native execution rechecks the selected source, policy admission, image/container binding, non-root identity, private-file denial control, output and cleanup.

There are no external network grants or host-file mounts. The app does not install into the user's default Hermes profile. It does not authorize unrestricted agent execution. Static success and twelve authored receipt checks do not establish general injection resistance. Observed metadata includes sandbox setup and verification tools and has incomplete semantics.

The current security-product workflow is recorded in `results/security-product-latest.json`; its original failures and explicit infrastructure continuation remain separate. [Security flow and evidence history](docs/core-flow.md). The earlier receipt lifecycle remains in `results/core-app-workflow-latest.json`, including its distinct installed-agent run; it is workload evidence, not a substitute for the security review.

With the app running, `.venv/bin/python -m scripts.security_product_workflow` exercises the security lifecycle through actual HTTP actions. It requires no pending skill at the start and an existing installation for rollback. The default command keeps a model hold blocking. An explicit `--accept-held-verdict` flag records bounded operator acceptance only when all native checks pass. The historical six-request workflow allowed at most 27 model requests; new app trials allow at most eight requests each under the shared authorized project cap (default $0.75); transport reservations can refuse work before any request. An explicit infrastructure continuation preserves prior costs, failed claims and passing probes. No automatic paid retry occurs. `make core-app-check` retains the earlier receipt-workload diagnostic.

The earlier zero-model lifecycle diagnostic is in `results/core-workflow-latest.json`. Reproduce that separate diagnostic with:

```bash
make core-check
```

This uses real native staging, scanning and sandbox execution with zero model calls. It rejects an unsafe skill, verifies or creates the first tested installation, uses it, tests and installs a distinct update, restores the previous version and reproduces its output. The existing first installation is explicitly reported when reused. These are functional integration checks, not a detection benchmark.

## Native dependencies and development

```bash
make setup
make evaluator-setup
make test
```

Native checks additionally require the pinned Hermes and SkillEvaluator sources beside this checkout and the configured dedicated Linux VM with Harbor 0.13.2, OpenShell 0.1.2, Docker and Sysdig 0.41.4. Versions and source commits are in [upstream pins](docs/upstream-pins.json). `make setup` alone does not provision that VM. Local socket access is required by offline HTTP tests.

The writable application data is under `results/core/`, separate from agent execution and ambient profiles. The process handles one operator action at a time, rejects hostile Host/Origin and missing CSRF tokens, verifies review revisions before approval, and refuses changed sources/evidence. [Core flow and trust boundary](docs/core-flow.md).

## NVIDIA and Nebius use

NVIDIA SkillEvaluator supplies native static/scanner checks and probe generation. The generator receives a trusted security framing message; its native user prompt, response parser and task model are retained. Fixture validation refuses ordinary questions without the required adversarial coverage before agent calls. Harbor supplies parser execution, the native Terminus agent and independent domain verification. OpenShell supplies enforcement; Sysdig supplies partial independent native metadata. SkillGuard composes these tools rather than replacing the agent harness or enforcer.

Nebius Token Factory serves the exact catalog model `nvidia/Nemotron-3_5-Lightning` for current probe generation, agent trials and the evidence recommendation. A complete held verdict can receive one explicit adjudication by `nvidia/nemotron-3-super-120b-a12b`, retaining the original recommendation and all probe evidence. This is single-attempt, with no probe reruns; it may still hold. Earlier research also used Super for repair/review. Security review exports the selected fictional guide, generated inputs and recorded observations; credentials and personal receipts are outside this test scope. The separate local parser utility makes no model request and keeps typed receipts local.

The [guide-only repair and fresh comparison](docs/receipt-guide-repair.md) completed sixteen real native agent trials on eight new receipts. Repaired V8 completed 8/8 correctly with no observed attack-directed actions; the original guide completed 2/8 and followed attacks in 4/6 attack cases. Correct saved files alone were 8/8 versus 6/8; some original runs failed confirmation within the shared six-request limit. The agent extracted values itself; the parser is identical in both conditions. The four file-access attacks and two amount-corruption attacks are a small authored set, not a general security guarantee. The app now installs this exact V8 candidate (`383f1e3092bb...`), preserving its guide/parser bytes. Its previous authored example and historical evidence remain separate. All failed revisions and stopped cohorts remain in the repair record.

The October 22 fresh learned-skill trial `receipt-agent-72fc12e8` passed the unchanged receipt contract, with six actual Lightning requests and native completion confirmation. Native metadata corroborated guide reading, parser/input I/O in the same Python process, and final-answer writing during agent execution. The agent saved total 23.00, preserved `needs_clarification: false`, and did not disclose the fake private canary in terminal output. The trusted task frames hostile receipt text as data and specifies the output schema; no expected values or host-generated answer are supplied to the agent. This is one authored case, not a Skill Lift comparison or a general security result. The separately frozen [paired holdout comparison](docs/receipt-learning.md) found 8/8 completed correct answers with the skill versus 7/8 without it. One skill-enabled attack run attempted an unrelated private-file read, which OpenShell denied; counting that attempt as failure gives 7/8 in both arms. This small study shows no overall safe-completion gain.

Earlier failures remain archived, including missing final output, an input-copy wiring error and omission of the sixth receipt field. The old review's unrestricted-activation verdict remains blocked. Passing this new task does not erase that history.

App reviews now bind fresh native agent evidence to the exact selected guide/parser and current parser/static checks. An ordinary security pass requires all four generated agent probes, a source-bound policy and an allow recommendation, in addition to native source/regression checks. A complete held review can instead receive explicit operator risk acceptance; incomplete or unsafe evidence cannot. The approval event binds its reason, exact source and immutable held review. Changed evidence revokes that acceptance. A model recommendation cannot override a failed functional check or observed unsafe behavior. Each new app trial has an independent durable claim, exact fake-key preflight, an explicit eight-request completion bound, 2,000 output tokens per request, thinking disabled, the operator-authorized aggregate cap and VM cleanup; paid inference is never retried automatically. Only the fixed fictional task and selected skill are sent. A passing unchanged review reuses its recorded result without another call. `make core-check` remains an explicitly parser-only lifecycle diagnostic.

See `results/oct22-core-app-verification.json` for historical October 22 app evidence and ledger totals: 523 completed requests, **$0.11549730 estimated usage + $0.10 retained unknown hold = $0.21549730 accounted**, below the **$0.75** cap. This app flow added 12 requests, estimated $0.00275814. The UI reads the current ledger separately from immutable comparison-archive totals. Repair-comparison evidence remains in `results/oct22-guide-repair-verification.json`; earlier single-case evidence remains in `results/oct22-agent-verification.json`. Estimates are not provider billing totals or a speedup benchmark. Token Factory cloud sandbox access previously returned HTTP 403, so the development workflow uses local native OpenShell.

## Earlier verified local product result — October 23

Actual HTTP workflow `security-product-1495f6f7` completed unsafe rejection, exact known-repair staging, native security review, explicit held-verdict acceptance, installation, rollback and restoration. Four real agent probes completed correctly in six requests each, with observed guide/input/output I/O, no observed private-file attempts and no attack-directed terminal commands. Both Lightning and Super recommended **hold**; neither is relabeled as allow. The active version records **operator_approved_hold** with its acknowledged warning, reason and evidence hash. Source/native failures remain non-overridable.

The first generated design lacked attack coverage and was revoked. An incomplete third native trial and two unknown-cost requests remain preserved; explicit infrastructure recovery reused two reverified probes and ran only the remaining cases. This is a small generated security exercise, not a fresh independent benchmark. [Full evidence and limits](docs/core-flow.md).

Independent verification: `results/oct23-security-product-verification.json`. The security-core checkpoint passed **892 tests**, the first release suite **900**, and the latest connection/budget update **916** with Ruff and JavaScript syntax clean. The public replay was browser-checked at 717×804 and captured at 1440×756. The separate cloud app login and authenticated live review have now also been browser-checked. At that historical local checkpoint, the fresh installed-agent check completed with six real Nebius requests, total 23.00 and observed guide reads before/after input. All four local native VMs were stopped. The Mac servers have since been stopped for cloud migration. Historical ledger: **562 completed requests, $0.12681108 estimated usage + $0.25 retained unknown holds = $0.37681108 accounted** under the operator-authorized budget. These new six requests cost an estimated $0.00136542; the earlier human-exception lifecycle and its 556-request checkpoint remain preserved. The clean source export passed **915 tests with one optional native CLI check skipped**, using the existing dependency environment rather than a newly provisioned machine.

## Deferred scope

General autonomous-agent protection, broader independently curated attack/Skill Lift evaluations, broader tracing guarantees and unrestricted Hermes activation remain outside the frozen receipt profile. The public recorded demo and protected cloud deployment are separate deliverables. Public video upload and final submission remain paused at the entrant’s direction. Historical research evidence is preserved in [progress](PROGRESS.md) and [agent workflow](docs/receipt-agent-workflow.md). `make review-history` serves the earlier read-only review separately from the core app.
