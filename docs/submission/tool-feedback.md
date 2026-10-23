# Feedback grounded in retained runs

## Nebius Token Factory

Used for generation, actual tool-using agent trials, initial review and one stronger-model adjudication. Catalog discovery and the OpenAI-compatible interface let the existing native evaluator and agent use the same inference service. Every call was bounded and logged; no custom inference server or model-weight deployment was needed. We did not measure onboarding time or a latency improvement.

Two requests in one native trial failed with unknown cost; six requests were forwarded but only four responses returned. We retained the holds rather than assuming zero cost. Better request IDs and a reconciliation endpoint for uncertain billing/outcomes would help low-budget evaluations. Local evidence does not establish the cause of those connection failures.

## NVIDIA Nemotron

Lightning completed the four retained agent probes in six requests each, with correct answers and completion confirmation. Disabling thinking was necessary for our bounded structured generation configuration; an earlier call exhausted the output limit in reasoning and produced no valid case JSON. A documented structured-output profile would reduce failed setup calls.

Lightning and Super both held the final review while acknowledging correct behavior and no prohibited actions. Their explanations treated the presence of malicious test text as incomplete resistance evidence. We preserved the warnings and exposed human acceptance separately. Distinguishing attack inputs, attempted actions, enforced denials and required missing evidence more reliably would improve security-review usefulness. This is feedback from this small workflow, not a model-wide benchmark.

## NVIDIA SkillEvaluator

We reused native Tier 1 checks, generation, task models and response parsing. The initial four-bucket generation returned ordinary questions despite attack guidance. A distinct adversarial-input mode with explicit category validation would help; a syntactically valid dataset is not evidence of adversarial coverage. See `docs/upstream.md` for retained reproductions and proposed improvements.

## Harbor / OpenShell

Harbor supplied the native agent and independent functional grader. Frontmatter delimiter whitespace silently affected discovery; our narrowly pinned wrapper normalizes only that boundary. A direct discovery diagnostic would be preferable.

OpenShell supplied confinement and native policy admission. The bounded receipt workspace denied the fake private file under a policy matching the declared contract. Clearer startup/PTY/identity diagnostics and explicit documentation of metadata-control limitations would shorten integration. SkillGuard does not add a replacement monitor or enforcer.

## Cloud sandbox onboarding

Token Factory sandbox access returned HTTP 403 and was not available to this account. We used local native OpenShell instead. No cloud sandbox, Serverless Jobs or Endpoints deployment is claimed. Clearer account-entitlement feedback would help.

We would reuse the inference interface and native tools for a broader evaluation, retaining independent evidence, request accounting and explicit scope rather than treating a model recommendation as the whole security boundary.
