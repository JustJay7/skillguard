# SkillGuard: Agent Instructions

## Mission
Build SkillGuard for the Nebius x NVIDIA Global AI Hackathon, Personal AI track.
Thesis: a personal AI agent must never silently learn a new behavior without proving what that behavior does.
SkillGuard intercepts skills a Hermes agent writes for itself, replays them in sandboxes against generated attack tests, records what they touch, shows a behavioral diff, decides pass/block with Nemotron, and turns the result into an OpenShell policy.

Deadlines: feature freeze Oct 23, 2026. Submission complete by Oct 28. Hard deadline Oct 30, 2026, 10:00am PT.

## Operating mode: build, don't ask
- Default to action. If a choice is ambiguous, pick the most reasonable option, log it in `DECISIONS.md` (decision, reason, how to reverse), and continue.
- Stop and ask ONLY for: secrets or credentials; spending beyond the budget below; pushing to a public remote, publishing, or deploying; deleting anything outside this repo; a blocker that survived 3 genuinely different attempts.
- Never end a turn with an offer or question if unblocked work remains. If `PROGRESS.md` has an unchecked task, start it.
- If one task is blocked, record it under "Blocked" in `PROGRESS.md` with what you tried, then move to the next unblocked task.

## Work loop (repeat until the task list is empty)
1. Read `PROGRESS.md`. Take the top unchecked task.
2. Write or extend a test first where practical.
3. Make the smallest change that passes.
4. Run tests and lint. Fix until green.
5. Tick the task in `PROGRESS.md`, commit with a clear message, continue.

Done means: you executed it and saw the output. Never claim something works without running it. When reporting, give the command and the result.

## Token discipline
- Don't reprint whole files. Make targeted edits.
- Search (`rg`/`grep`) before opening files. Read only the relevant lines.
- Status updates: 5 lines max. Don't narrate plans; execute them.
- Don't regenerate unchanged code. Don't explain code unless asked.

## Phase 0 gates: must pass before any feature work
Record every finding in `docs/findings.md`.
1. Find where Hermes Agent writes and loads skills. Intercept a skill write (hook or file watch).
2. Capture a trace of file, network and process activity from a skill running inside the sandbox.
3. Determine whether OpenShell policy can be scoped per skill or only per sandbox. If only per sandbox: design for one sandbox per skill execution, and note the cost and latency impact.
4. Check Token Factory Sandboxes access. If not granted, fall back to OpenShell on a Nebius Serverless Job and continue.
5. Install NVIDIA SkillEvaluator (https://github.com/NVIDIA/SkillEvaluator), pinned to a specific commit. Confirm Hermes saves skills in the Agent Skills format (folders with `SKILL.md`) so SkillEvaluator can read them directly.
6. Check which agents SkillEvaluator's Tier 3 live evaluation supports and whether Hermes can be one. If not, record what an adapter would take, and use a supported agent for Skill Lift runs in the meantime.
If gate 1 or 2 fails after real effort, stop and report. That is a pivot decision for the human.

## Architecture rules
- Core primitive: the behavioral envelope (paths read/written, network hosts, processes, tools called). Build it once and reuse it everywhere:
  - behavioral diff = compare two envelopes
  - least-privilege policy = envelope → OpenShell rule
  - versioning and rollback = stored snapshots of skill + envelope
- Reuse NVIDIA SkillEvaluator for static validation (Tier 1, including SkillSpector) and Skill Lift (Tier 3). Point it at Token Factory through its `openai-compatible` provider settings (`SKILL_EVAL_LLM_BASE_URL`, `SKILL_EVAL_LLM_MODEL`, `SKILL_EVAL_LLM_API_KEY`). Do NOT rebuild static scanning, eval-dataset generation or the sandboxed agent harness. Our code is the delta: runtime interception, behavioral envelope and diff, verdict, OpenShell rule.
- Any fix or feature that belongs in SkillEvaluator itself: note it in `docs/upstream.md` as a candidate pull request.
- Do NOT build runtime monitoring or enforcement. OpenShell already blocks unapproved network hosts and asks the operator. Our job is generating the rules.
- Keep `main` working at all times.

## Unknown APIs
Never guess function names, endpoints or config keys for Hermes, NemoClaw, OpenShell, Token Factory or the Sandboxes SDK. Read the installed package source or official docs first, then log what you learned in `docs/findings.md`.

## Models and cost
- Inference: Nebius Token Factory (OpenAI-compatible API). On first run, list available models from the API and use the exact IDs returned. Don't hardcode guessed IDs.
- Routing: Nemotron 3.5 Lightning by default (test generation, extraction, triage). Nemotron 3 Super for trace analysis. Nemotron 3 Ultra only for final verdicts on uncertain cases. Nemotron Content Safety as a second opinion.
- Bulk work (test generation, benchmark runs) goes through the batch API.
- Total budget: $50 in credits. Log tokens and estimated cost for every call to `results/cost_log.csv`. Abort any single benchmark run that exceeds $2.
- Unit tests run offline against recorded model responses in `tests/fixtures/`. Live API calls only in tests marked `live`.

## Project safety
- Attack tests may only send data to a local endpoint we control (e.g. a localhost canary server).
- Use fake canary secrets only. Never real credentials.
- Never commit keys. Use `.env` (gitignored) plus `.env.example`.
- Any staged attack in the demo is labeled as staged.

## Honesty
- Never invent metrics. Every number in the README, dashboard or video must come from a script output saved in `results/`, alongside the command that produced it.
- If something doesn't work, say so in `PROGRESS.md`. Don't paper over it.

## Code standards
Python 3.12+ (SkillEvaluator supports 3.12 and 3.13), type hints, pytest, ruff. Small modules. One-command setup (`make setup`). One-command test (`make test`).

## Build order after Phase 0
1. Full loop on one planted skill: intercept → SkillEvaluator checks → generated attack tests → sandbox replay → envelope → diff → Nemotron verdict → OpenShell rule. Add versioning and rollback.
2. SkillBench: labeled benign and malicious skills with functional checks. Primary comparison: SkillEvaluator alone vs SkillEvaluator + SkillGuard on the same skills. Also report static-only, LLM-only and sandbox-only. Report detection rate, false positives, cost and latency. Report whatever the numbers show, including cases where SkillEvaluator alone is enough.
3. Least-privilege rule generation.
4. Dashboard centered on the behavioral diff, with attack replay.
5. Repair, only if the repaired skill passes a held-out set of attack types the repair step never saw.
6. Lightning → Super → Ultra escalation test, only if ahead of schedule.
Out of scope: memory poisoning (roadmap only), extra assistant features unrelated to the thesis.

## Submission checklist (verify before Oct 28)
- Apache-2.0 or MIT license visible on the repo page
- README: one-line pitch, setup, "How we use NVIDIA models" (model ID, role, why), "Where Token Factory accelerated us" (real numbers), other Nebius services used, known limitations
- Hosted demo URL with test access
- Public YouTube video under 3 minutes, with audio naming Token Factory and the Nemotron models used
- Written feedback on Nebius and NVIDIA tools (specific bugs, doc gaps, requests)
