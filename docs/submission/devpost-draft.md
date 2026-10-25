# SkillGuard

## Tagline
The receipt answer is right. The new skill is still unsafe. SkillGuard catches the difference.

## Track
Personal AI.

## Project and testing links

- Public MIT-licensed source/test build: https://github.com/JustJay7/skillguard
- Guided read-only evidence walkthrough: https://skillguard-evidence-demo.jaymalhotra.chatgpt.site/
- Optional protected development app: https://literate-space-system-45gjq9qjggwfjw7p-8770.app.github.dev/
- Video: finished live-run recordings remain local. Add the actual public YouTube URL only after the entrant authorizes upload.

The source/test build and its setup guide are the durable project route. The walkthrough is explicitly a replay; Codespaces is an optional live development environment that can suspend. The judge access code belongs only in the private testing field, never the description or repository. See the testing instructions for the native runtime requirements and current access limits.

## Inspiration

An assistant that learns reusable skills can accidentally preserve a bad behavior. Receipt organization makes the risk concrete: a receipt should never become permission to read an unrelated private note or alter a purchase total. We built an explicit checkpoint between a proposed skill and its installation.

## What it does

Hermes proposes a skill through its native pending-write gate. SkillGuard preserves its exact source and has Harbor's Terminus test agent exercise it inside OpenShell before approval for the restricted Hermes profile. The operator sees source checks, observed behavior, generated attacks and a model recommendation, then can approve, reject or roll back.

Our strongest example looks functionally correct. The repaired V8 parser plus one unrelated fake-file read produces all twelve expected receipt outputs. NVIDIA SkillSpector's pinned static-only scanner rates it **7/100, SAFE**, the same as the repaired control. SkillEvaluator Tier 1, including security and code-risk checks, passes it too.

Actual OpenShell execution records thirteen denied private-file opens, including one independent control. There are zero reported private read bytes. SkillGuard blocks installation even though the receipt answers are correct—and even when Nemotron incorrectly recommends allow. The native gate is authoritative; favorable model advice cannot override failed checks.

These are authored fictional examples, not a broad benchmark. SkillSpector's optional model-based scanner stage was not tested.

## How we built it

SkillGuard combines native Hermes staging, NVIDIA SkillEvaluator scanning and probe generation, Harbor agent execution, OpenShell confinement and partial independent Sysdig observations. Our contribution is source/evidence binding, behavioral envelopes and differences, policy compilation, explicit approval lineage, versioned installation and rollback.

Nebius Token Factory serves real **NVIDIA Nemotron 3.5 Lightning** (`nvidia/Nemotron-3_5-Lightning`) calls for generation, the tool-using test agent and evidence review. **Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b`) supports one adjudication of a complete held review. The server keeps its API key outside candidate sandboxes and enforces request, token and aggregate accounting limits.

The current clean Python 3.12 source extraction passes **1032 tests**, with lint clean, after the documented `make test-deps` install. The exact scanner/native comparison, source hashes and current run status are retained in the source evidence and comparison document. The cloud runtime has its own isolated Linux/OpenShell VM; no Nebius AI Cloud or hosted Token Factory Sandboxes usage is claimed.

## What we learned

A correct answer can coexist with an unsafe action. Static analysis, task grading and a model's opinion each miss different things; source-bound native evidence must remain a separate gate.

The first revised reviewer confused the excess denials with the single trusted control. Its incorrect allow and the application's correct block remain preserved. Future review evidence names the excess count and separates functional success from security success. Earlier holds are not deleted or relabeled; the fresh repaired review is recorded separately.

A prior small skill/no-skill study found 7/8 safe completions in each arm, showing no overall gain. A separate guide-repair study improved confirmed correct completions from 2/8 to 8/8 on eight new authored receipts. Those experiments answer different questions and do not establish general safety.

## What's next

Broader skill domains and independently curated evaluations. The current product deliberately supports a fixed receipt workspace, a known repair recipe and explicit human approval; it does not train model weights or autonomously repair arbitrary code.

## Tool feedback and final entrant fields

Concrete Nebius/NVIDIA feedback is in `tool-feedback.md`. Complete team/ownership and eligibility declarations in Devpost, select Personal AI, and select a Builders & Brews city only if actually attended. Do not invent attendance, an uploaded video URL or unattended hosting.
