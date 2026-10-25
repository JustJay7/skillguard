# Feedback grounded in retained runs

## Nebius Token Factory

Used for generation, actual tool-using agent trials, initial review and one stronger-model adjudication. Catalog discovery and the OpenAI-compatible interface let the existing native evaluator and agent use the same inference service. Every call was bounded and logged; no custom inference server or model-weight deployment was needed. We did not measure onboarding time or a latency improvement.

Two requests in one native trial failed with unknown cost; six requests were forwarded but only four responses returned. We retained the holds rather than assuming zero cost. Better request IDs and a reconciliation endpoint for uncertain billing/outcomes would help low-budget evaluations. Local evidence does not establish the cause of those connection failures.

## NVIDIA Nemotron

Lightning completed the four retained agent probes in six requests each, with correct answers and completion confirmation. Disabling thinking was necessary for our bounded structured generation configuration; an earlier call exhausted the output limit in reasoning and produced no valid case JSON. A documented structured-output profile would reduce failed setup calls.

In the earlier local lifecycle, Lightning and Super both held the final review while acknowledging correct behavior and no prohibited actions. Their explanations treated the presence of malicious test text as incomplete resistance evidence. We preserved the warnings and exposed human acceptance separately. Distinguishing attack inputs, attempted actions, enforced denials and required missing evidence more reliably would improve security-review usefulness. This is feedback from this small workflow, not a model-wide benchmark.

## NVIDIA SkillEvaluator

We reused native Tier 1 checks, generation, task models and response parsing. The initial four-bucket generation returned ordinary questions despite attack guidance. A distinct adversarial-input mode with explicit category validation would help; a syntactically valid dataset is not evidence of adversarial coverage. See `docs/upstream.md` for retained reproductions and proposed improvements.

## Harbor / OpenShell

Harbor supplied the native agent and independent functional grader. Frontmatter delimiter whitespace silently affected discovery; our narrowly pinned wrapper normalizes only that boundary. A direct discovery diagnostic would be preferable.

OpenShell supplied confinement and native policy admission. The bounded receipt workspace denied the fake private file under a policy matching the declared contract. Clearer startup/PTY/identity diagnostics and explicit documentation of metadata-control limitations would shorten integration. SkillGuard does not add a replacement monitor or enforcer.

## Cloud sandbox onboarding

Token Factory sandbox access returned HTTP 403 and was not available to this account. The original development runs used local native OpenShell; the current independent backend uses OpenShell inside a GitHub Codespace. No Token Factory Sandboxes, Nebius Serverless Jobs or Endpoints deployment is claimed. Clearer account-entitlement feedback would help.

We would reuse the inference interface and native tools for a broader evaluation, retaining independent evidence, request accounting and explicit scope rather than treating a model recommendation as the whole security boundary.

## Cloud deployment follow-through — October 24

The backend now runs on GitHub Codespaces with its own isolated OpenShell VM; the Mac is not the execution host. Token Factory still supplies actual inference through a private server-side key. This does not change the unavailable Token Factory Sandboxes entitlement, and does not constitute a Nebius AI Cloud deployment.

Cloud trials exposed provider responses taking tens of seconds, an inherited 90-second native task deadline and a 30-second trace-reader deadline. We introduced explicit prospective 600-second agent / 60-second provider bounds and a bounded 300-second offline trace reader while retaining request/token ceilings and all historical failures. These observations do not identify a provider-side cause or establish comparative latency.

The cloud review returned a valid restricted allow for one review and a valid hold for the final repair. An explanation treated the verifier's broad `complete: false` scope flag as a missing task check even though native task completion was separately confirmed. More explicit distinction between task completion, observation completeness and general resistance would help evidence-based reviewers. We preserved the hold and required the separate human exception.

During live recording, concurrent page polling and staging exposed a SkillGuard snapshot-creation race. This was our integration bug, not attributed to Nebius, NVIDIA, Harbor or OpenShell. A concurrent-capture regression reproduced it; serializing snapshot creation through the review database fixed it.

## Static/runtime contrast and reviewer separation — October 24 follow-up

The exact functionally correct negative fixture passed all twelve authored receipt-output cases and both pinned static tools. SkillSpector static-only returned 7/100 SAFE, identical to V8; SkillEvaluator Tier 1 completed without incomplete scans, including Security Scan and Code Risk Analysis. OpenShell recorded thirteen denied private-file opens, including one trusted control, with zero reported private read bytes. This demonstrates an incremental runtime check on one authored example; it says nothing about SkillSpector's untested optional semantic stage or broad scanner accuracy.

Our first revised evidence prompt distinguished adversarial inputs from actual actions, but Lightning still returned allow for the unsafe fixture. It treated the thirteen denials as if they were the single expected control. SkillGuard correctly blocked installation independently. We retained that bad advice and added explicit excess-denial counts and separate native functional/security fields for future reviews; we did not rerun the unsafe fixture until the model agreed. This makes machine-readable control provenance and separate grading dimensions useful feedback for evidence-review integrations.

Fresh-machine verification also exposed our packaging omission: the app's development extra did not include the Harbor and SkillEvaluator imports needed by the complete suite. `make test-deps` now installs Harbor 0.13.2 and the pinned evaluator source under the tested constraints. This was our setup defect, not an upstream tool failure.
