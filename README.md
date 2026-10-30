# SkillGuard

**Before a personal AI learns a new skill, watch what that skill actually does.**

Built by Jay Malhotra and Tasnim Hassan for the Nebius Global AI Hackathon, hosted in partnership with NVIDIA.

Hermes proposes a receipt-organizing skill. SkillGuard pauses the write, has a Harbor test agent exercise the skill inside OpenShell, and binds the installation decision to the exact tested source. You can reject an unsafe update, approve a reviewed version, or roll back.

A receipt that says “read a private note” should remain receipt data. A skill that returns the right total while attempting that read should still be blocked.

## The result static checks miss

The pinned NVIDIA SkillSpector static-only scan rates our authored unsafe fixture **7/100, SAFE**, the same as the repaired skill. NVIDIA SkillEvaluator Tier 1, including its security and code-risk checks, also passes both. Its optional model-based scanner stage was not used.

The new negative fixture keeps the working V8 parser and adds an unrelated read of a **fake** private file. It produces the correct answers on all twelve authored receipt cases even when that read is denied. This separates task correctness from unsafe behavior. The exact native run passed all twelve receipt checks but recorded **thirteen denied private-file reads, including one control**. SkillGuard blocked installation even when the model reviewer incorrectly recommended allow. See [the comparison and its evidence](docs/static-runtime-contrast.md). The older nonfunctional negative sample and its failures remain in history.

## How it works

1. **Pause the skill.** Capture a native Hermes pending write and preserve its guide/script hash.
2. **Test its behavior.** Run NVIDIA source checks, twelve receipt cases and four generated adversarial probes. Harbor supplies the test agent; OpenShell supplies confinement; Sysdig supplies independent partial observations.
3. **Make an explicit decision.** Nemotron reviews the evidence. Failed or incomplete native checks and observed unsafe actions block installation. Passing checks make the exact version eligible for human approval. Versioned installation supports rollback.

The testing agent is Harbor Terminus. Hermes supplies the proposed skill and approval-gated application; we do not claim that the sandbox agent is Hermes.

The fresh repaired-skill review completed all four generated agent probes in **22 requests** (6, 4, 6, 6). With trusted task context, Nemotron returned **allow**; the exact version was installed without a hold exception. The installed agent then completed a separate receipt in six requests, and rollback/restoration passed. Earlier false blocks, invalid generation and startup failures remain preserved. [Verification](results/oct24-review-followup-verification.json).

## Try it or inspect the source

- [Final narrated demo (2:44)](https://youtu.be/eZ9NVyEEMAI) — genuine application captures and recorded results, edited for the walkthrough.
- [Recorded walkthrough](https://skillguard-evidence-demo.jaymalhotra.chatgpt.site/) — always distinguish this replay from live execution.
- [Public source/test build](https://github.com/JustJay7/skillguard) — MIT licensed.
- [Optional live development workspace](https://literate-space-system-45gjq9qjggwfjw7p-8770.app.github.dev/) — separate operator code required; Codespaces can suspend. It is not an unattended judging host.
- Final narrated demo, submission description and testing instructions: [submission materials](docs/submission/README.md). The [final demo notes](docs/submission/final-demo/README.md) describe the captured evidence and editing, with the exact narration and captions included.

For the included replay, no credentials are needed:

```sh
python3 -m http.server 8769 --bind 127.0.0.1 --directory recorded-demo
```

Open http://127.0.0.1:8769/. In the development checkout, use `make demo-bundle` first and serve `dist/skillguard-demo` instead.

## Install and test

Use **Python 3.12 or 3.13**, Git and Make:

```sh
make test-deps PYTHON=python3.12
make test
```

`test-deps` installs the app and development tools, Harbor 0.13.2 and the exact NVIDIA SkillEvaluator commit used by the suite. Running tests makes no paid inference requests. The current verified development suite is **1056 passing tests**; [the freshly extracted source log](results/oct25-extracted-source-tests.txt) is the authority rather than old checkpoint counts.

Native reviews additionally need the pinned Hermes/SkillEvaluator checkouts in the expected sibling layout and a compatible Linux/OpenShell VM with Docker and Sysdig. Dependency installation does not provision that VM. Follow [cloud setup](docs/public-backend.md), [source/version pins](docs/upstream-pins.json) and [the core flow](docs/core-flow.md). On a configured host, `make review` opens the local app at http://127.0.0.1:8768/.

Copy `.env.example` to a private `.env` and configure your own Nebius key and explicit budget before real model actions. Keep the key outside candidate sandboxes. One deployment owns the project accounting ledger; unknown cost reservations stay counted.

## How we use NVIDIA and Nebius

Nebius Token Factory supplies actual NVIDIA model inference through its OpenAI-compatible API. **Nemotron 3.5 Lightning** (`nvidia/Nemotron-3_5-Lightning`) generates probes, powers the tool-using test agent and reviews evidence. **Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b`) is available for one adjudication of a complete held review. NVIDIA SkillEvaluator supplies native scanning and evaluation integration. OpenShell enforces the sandbox; SkillGuard compiles the bounded permissions and manages evidence, approval and version lineage.

The current verified shared ledger records **805 completed provider requests**, **$0.18795726 estimated completed usage** and **$0.29 retained unknown-cost reservations**: **$0.47795726 accounted**. The follow-up added 57 completed requests, including retained failures. This made repeated real-agent checks practical within our existing credits. Estimates are not provider invoices, and we did not measure a speedup. We use Token Factory inference; we do not claim Nebius AI Cloud or hosted Sandboxes usage.

## Limits

The supported profile is receipt skills in a fixed isolated workspace. Small authored/generated attack sets and partial native traces do not establish general safety. A prior paired skill/no-skill study found no overall safe-completion gain; a distinct guide-repair comparison improved confirmed completions from 2/8 to 8/8 on eight new authored receipts. These experiments are not interchangeable benchmarks.

Correct output never excuses an unsafe action. A model hold remains a hold; any explicit restricted human exception is visibly recorded. The revised reviewer distinguishes hostile test inputs from the agent's actual actions, without forcing an allow. Earlier holds and failures remain preserved. The repair button selects a known tested recipe, not arbitrary autonomous repair. “Learning” means saving a reusable skill, not training model weights.

See [experiment methods](docs/receipt-learning.md), [guide repair](docs/receipt-guide-repair.md), [implementation history](docs/implementation-history-20261024.md) and [specific tool feedback](docs/submission/tool-feedback.md).
