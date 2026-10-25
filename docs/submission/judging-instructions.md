# Testing SkillGuard

## Primary source/test build and optional live access

Start with the public repository README. On Python 3.12 or 3.13, run `make test-deps` then `make test`; this installs the pinned Harbor/SkillEvaluator test adapters and runs the complete offline suite without model calls. The exact scanner-versus-native case study is in `docs/static-runtime-contrast.md`, with the labeled functional negative fixture under `skills/unsafe-functional/`. Never install that negative fixture.

Native execution additionally requires the pinned virtualization/OpenShell stack and private inference configuration described below. The source is not a preprovisioned VM. The public walkthrough is a read-only evidence tour. These paths must not be described as an always-running native backend.

## Links and access

Actual app: https://literate-space-system-45gjq9qjggwfjw7p-8770.app.github.dev/

Public source: https://github.com/JustJay7/skillguard

Use the demo access code supplied separately in the private submission testing field. It is not a Nebius API key. The supervised shared workspace contains fictional receipt skills only; please do not enter personal receipts, credentials or arbitrary code. Model calls use the server's private Nebius configuration and enforce the remaining project budget.

GitHub may first display its development-port notice. After entering the code, the banner must say **PUBLIC LIVE BACKEND · GitHub Codespaces**. The separate `chatgpt.site` walkthrough is an older recorded evidence replay, not this application.

## Inspect the working result without inference

1. Check the installed skill, native checks, four generated probes and model recommendation.
2. Expand **What the agent did** to see the actual recorded tool actions. The receipt answer includes vendor, date, subtotal, tax, total and clarification state.
3. Expand the generated probes to inspect malicious annotations and the agent's commands. These are small authored/generated exercises, not a blind benchmark.
4. Inspect **Evidence E3** for the declared OpenShell policy. The source, review and installation are hash-bound.

A held review remains held even after a human exception. A successful task does not mean general safety. Historical failed runs and reviews remain accessible.

## Exercise the live lifecycle

Each security review starts real native work and may take several minutes on this two-core development host. Do not repeat a click while it is running.

1. With no pending skill, choose **Stage unsafe sample**. This stages a fictional script that reads a fake private note through the native Hermes pending-write gate.
2. Choose **Review skill security**. Source/native checks fail and installation is blocked; a model cannot override that failure.
3. Choose **Stage known repair and review it**. This archives the rejection, stages the exact known V8 receipt repair and starts new checks. It is a known repair, not general autonomous code editing.
4. Inspect the four actual agent probes and recommendation. If all native checks pass and the model allows, acknowledge the restricted scope and install. If it holds, the optional exception requires both warning acknowledgment and a written reason. Do not override failed, incomplete or unsafe native evidence.
5. Expand **Receipt workload diagnostics** and choose **Run installed agent · fictional receipt**. This starts a fresh model/tool run on a fixed receipt containing hostile instructions. The agent reads the skill, extracts the correct purchase and writes its own answer; it is distinct from the zero-model parser diagnostic.
6. Choose **Restore previous version** to verify recovery. The exact prior tested installation and its warning state are retained.

## Hosting limitation requiring an entrant plan

Codespaces stops when idle or when included usage is exhausted. It is not an always-on judging service. The owner can resume the same deployment using the private restart launcher; judges cannot operate that owner-only launcher. The entrant must arrange availability through December 15 before treating live judging access as complete. Do not promise unattended uptime or ask judges to keep the development host alive.

The public repository also contains the functional source/test build, pinned native setup instructions and offline tests. `make setup` alone does not provision the nested Linux/OpenShell runtime. Native execution needs the documented virtualization-capable host; a recorded walkthrough is not a substitute for that runtime.
