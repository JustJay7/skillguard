# SkillGuard

## Tagline
Your personal AI can learn new skills. SkillGuard makes it show what changes first.

## Recorded walkthrough
https://skillguard-evidence-demo.jaymalhotra.chatgpt.site — recorded evidence only; the native review backend is local.

## Inspiration
A receipt is supposed to be data. For a personal assistant that writes reusable skills, a malicious instruction inside that receipt can become tomorrow's behavior. We wanted a clear boundary between an assistant proposing a skill and being allowed to keep it.

## What it does
SkillGuard pauses native Hermes skill writes before activation. It snapshots the source, runs NVIDIA SkillEvaluator checks, generates adversarial annotations, tests an actual agent inside OpenShell and records a behavioral envelope. The review shows changes, tool actions and declared permissions. Nemotron supplies an evidence-referenced recommendation. Installation requires the exact reviewed version and an explicit decision; rollback preserves the previous version.

The working runtime profile is receipt organization. It is a personal-AI learning gate, not a general-purpose security guarantee or an enterprise deployment platform.

## How we built it
Nebius Token Factory serves NVIDIA Nemotron 3.5 Lightning for generation, real agent trials and initial evidence review. One Nemotron 3 Super adjudication is available for a complete held review. Model IDs are `nvidia/Nemotron-3_5-Lightning` and `nvidia/nemotron-3-super-120b-a12b`.

NVIDIA SkillEvaluator supplies the existing scanner and dataset generator. Harbor supplies the Terminus agent and independent functional grading. OpenShell supplies native isolation and enforcement, with partial independent metadata from Sysdig. SkillGuard adds interception, evidence binding, envelopes/diffs, review decisions, bounded policy compilation, approval lineage and rollback. It does not replace those tools with a custom agent loop or enforcer.

## What actually worked
The recorded HTTP lifecycle blocked the staged unsafe skill, staged the exact known repair, verified four real native agent probes, installed by explicit human exception, rolled back and restored the tested version. All four probes completed correctly in six model requests each. The agent read the guide, handled untrusted annotations, saved the original purchase total and confirmed completion; these four trials did not invoke the parser.

Both Lightning and Super still recommended hold. We kept those warnings. The installation is labeled `operator_approved_hold`, not a model security pass. Explicit warning acceptance and a written reason cannot override failed/incomplete native checks, recorded private-file attempts, changed source or a blocked model verdict.

An earlier incomplete trial remains incomplete: six forwarded requests, four responses and two unknown-cost outcomes. Recovery reused two reverified passing probes and ran only remaining cases. There was no skill/input/grader change and no fresh independent benchmark claim.

Entire project accounting at the verified run: $0.12544566 estimated inference usage plus $0.25 retained unknown-cost holds, totaling $0.37544566 against a $0.75 cap. These are local estimates, not provider billing totals. Source: `results/oct23-security-product-verification.json`. No latency speedup or general detection-rate claim is made.

## Challenges and lessons
Source checks alone did not settle behavior. SkillEvaluator's native starter generation initially returned ordinary questions rather than attacks; we retained that failure and added trusted security framing plus coverage validation. Harbor discovery was sensitive to frontmatter delimiter whitespace, requiring a narrow source-pinned compatibility wrapper. Provider failures consumed request allowances, so durable claims and retained unknown-cost holds mattered. Correct output did not eliminate the need to inspect actions or preserve model uncertainty.

## What's next
Broader skill domains, independently curated benchmarks and more complete native attribution. Cloud sandbox access was unavailable; the working runtime is local native OpenShell. Public judging access, video and submission remain separate release tasks. A recorded walkthrough is provided for inspection; it is not a live model backend.

## Built with
Python, JavaScript, Hermes Agent, NVIDIA SkillEvaluator, NVIDIA Nemotron, Nebius Token Factory, Harbor, OpenShell, Sysdig, Lima, Docker.
