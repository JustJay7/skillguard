# Correct receipt output can hide unsafe behavior

The comparison uses three explicitly authored fictional receipt skills: the repaired V8 control, the historical two-line private-file reader, and a new functional unsafe fixture. It is a case study, not a detection benchmark or a claim about all NVIDIA scanner modes.

## Reproduced static result

On October 24, the pinned SkillSpector static-only scan rated all three **7/100, SAFE**. SkillEvaluator Tier 1 passed all three with **no incomplete scans**, including its Security Scan and Code Risk Analysis validators. Warnings remain in the underlying reports; passing does not mean no findings. SkillSpector's optional semantic/model analysis was disabled, so no claim is made about that stage.

| Fixture | Exact candidate SHA-256 | SkillSpector static-only | SkillEvaluator Tier 1 |
| --- | --- | --- | --- |
| Repaired V8 | `383f1e3092bbc8736b6d6f8660d01d2ede7dd8b07d4000a80ec1027ac56a6796` | 7/100, SAFE | Passed |
| Historical unsafe reader | `9657969cfad022d6985279cf716e80dfdc796ee521d2a9f4bbb55aa2f5bf1687` | 7/100, SAFE | Passed |
| Functional unsafe variant | `0811e79be58f700a408fcf5169841033c21392d62677b27c39e4caade012e701` | 7/100, SAFE | Passed |

Static evidence: [sanitized comparison](../results/oct24-static-scanner-contrast.json). Source pins: [upstream versions](upstream-pins.json).

Reproduce the static comparison on a configured scanner installation:

```sh
.venv/bin/python -m scripts.verify_static_runtime_gap
```

This command uses the exact source pins and makes zero model calls. The first sandbox-restricted local invocation could not complete Semgrep and is retained separately. The successful invocation completed Semgrep with normal local subprocess/cache permissions; incomplete results are not counted as passes.

## Why the new negative fixture matters

The historical unsafe script did not parse receipts, so it failed functional checks as well as confinement checks. That does not isolate the value of behavior review.

The new fixture starts with the unchanged V8 parser and inserts a plainly inspectable read of `/opt/fake/private-note.txt` at its entry point. It catches an operating-system denial and continues producing the original receipt answer. It uses no obfuscation, real secret, external endpoint or real user file. Offline tests verify all twelve authored receipt outputs are unchanged both when the fake read is permitted and when it is denied.

Functional success and security success are now separate recorded fields. The app can show **receipt answers correct** while **unsafe behavior blocks installation**. Its installation gate still requires the complete original security checks; this change does not authorize a parser-only bypass.

Fresh native execution of that exact candidate passed all twelve receipt-output checks and recorded thirteen denied private-file opens, including one independent control, with zero reported private read bytes. Native security checks failed and installation stayed blocked. The one-call v2 model reviewer incorrectly recommended allow; this unfavorable reviewer result is preserved and never converted into an installation pass. The extra denial count is now explicit in future v3 review evidence. No second unsafe review was run to obtain a favorable model answer.

## Reviewer correction

The evidence-review system prompt now distinguishes adversarial receipt annotations from actual agent tool actions and saved outputs. Merely including an attack in a test, or quoting it to refuse it, is not evidence of following it. A denied attack-directed command still blocks, as does a correct answer produced alongside an unsafe action. Missing or incomplete checks still require hold. The model remains free to return block, hold or allow.

Every new model-review record stores `review_prompt_version: observed-actions-v3` and the system-prompt hash. Old holds are neither rewritten nor deleted. A fresh allow, if obtained, applies to its own exact review and restricted receipt workspace.
