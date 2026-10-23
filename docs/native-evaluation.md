# Native frozen-resource evaluation

This is a bounded NVIDIA SkillEvaluator/Harbor integration, not a live-agent
evaluation, Skill Lift result, generated attack benchmark or activation path.
The legacy route accepts only the original unchanged native pending receipt
parser, candidate `93fb1091fe81fe4a9fb5b6f8305546db793cc45df7984c8b7d5204d3a5661ef9`.
The frozen-contract route also accepts a native staged repair bound to that
original and the same committed test inputs. See [receipt workflow](receipt-workflow.md)
for the current repaired candidate and twelve-case result.

Run `make native-eval` after installing the pinned dependencies and existing
`sgtrace-clean` runner. Preparation requires SkillEvaluator commit
`33eb9dc74a09280bebf6fb4c921d290a0f874713` with its `tier3` extra. The guest
requires Harbor 0.13.2 at `/opt/skillguard-harbor/bin/harbor` and Docker Compose
(installed version 5.6.0). No host mounts, agent forwarding or provider key.

Host Semgrep 1.178.0 coexists with Harbor using `opentelemetry-api==1.37.0` and
`fastapi==0.141.1`. Unconstrained installation upgraded telemetry incompatibly;
these compatible versions were restored. `pip check` is clean. Fresh native
Tier 1 passed with all scans complete after installation. An earlier restricted
invocation could not read system trust anchors; that incomplete report is
preserved separately from the verified passing invocation.

Preparation copies the archived candidate into a private run directory, leaving
pending bytes unchanged. Native `create-eval-dataset --full --no-llm` generates
four template entries from authored guidance, including an unrelated negative
example. Native `init-harbor-task` scaffolds a BYOT task. Native strict contract
validation and Harbor's actual Task schema both validate it. The task has four
authored fictional input/output checks, not four generated attacks or four
independent agent trials.

Harbor's built-in oracle executes the frozen resource in Docker inside the
dedicated Linux VM. Our domain grader checks JSON output; NVIDIA's existing
`custom_grader_runner.py` normalizes its rich reward for Harbor. The task is
configured for UID/GID 1000, network disabled, capabilities dropped, no new
privileges and source/input without write permissions. These settings are not
an OpenShell enforcement proof or independent syscall trace. Native Harbor owns
execution/container cleanup; the wrapper stops the VM in a `finally` block.

Native Harbor collects outputs and the executed parser. The operator verifies
the parser hash and independently recomputes the reward before persisting it.
The review archives the trial, reward, source, expectations and outputs with
hashes. Metadata-only E10 exposes outcomes without receipt values. It remains
partial, has no Skill Lift, invalidates older advice and cannot permit
activation. Hash consistency is not authenticity against an operator who can
rewrite all artifacts and the store.

Historical original-parser run `native-eval-06f3975f`: one oracle trial completed without exceptions;
all four domain checks failed. Clear and instruction-laden inputs yield the
same wrong output. The subtotal is selected as total, a labeled ISO date is
missed, and contradictory totals are not left null. The instruction-laden check
fails functionality; it does not demonstrate an instruction-induced leak,
network absence or live-agent injection resistance. Candidate unchanged/inactive.

```sh
.venv/bin/python -m scripts.prepare_native_evaluation
.venv/bin/python -m scripts.run_native_evaluation
make test
.venv/bin/python -m pip check
```

Historical checks at that milestone: 243 tests passed, Ruff clean, both retained Linux VMs read
back as Stopped. Zero inference requests or cloud resources. Private artifacts:
`results/integration/native-eval-06f3975f`; summary:
`results/native-evaluation-latest.json`.

Retained failures: invalid network enum accepted by presence-only validation
(`native-eval-0a0b9bb3`); missing Compose (`native-eval-b04a3fcb`); rich reward
without NVIDIA's normalizer (`native-eval-b4e0bf25`). Never counted as successful
evaluation. `native-eval-71734c84` is the first completed domain trial, preceding
automatic persistence and final VM cleanup.

Broader independent runtime semantics, upstream live-agent evaluation with
declared model-input privacy and bounded spending, Hermes/OpenShell registry
integration, executable installed baseline, activation/rollback, benchmarks and
submission remain open.
