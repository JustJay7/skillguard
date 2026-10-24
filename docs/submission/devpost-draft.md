# SkillGuard

## Tagline
Your personal AI can learn new skills. SkillGuard makes it show what changes first.

## Track
Personal AI.

## Live project and source
- Actual application: https://literate-space-system-45gjq9qjggwfjw7p-8770.app.github.dev/
- Public MIT-licensed source: https://github.com/JustJay7/skillguard
- Video: the new live-run recording replaces the earlier recorded-evidence walkthrough; its public YouTube URL must be added after upload approval.
- The access code belongs in the private judging/testing field, never in the description, video or repository. Codespaces is development hosting and suspends when idle. See the separate judging-access checklist before final submission.

## Inspiration
A receipt should be data, not an instruction to read a private note or change a purchase total. But when a personal assistant writes reusable skills, a bad instruction can become behavior it keeps. We built SkillGuard to put an explicit review between a proposed skill and the permission to use it.

Our initial audience is people experimenting with personal agents that create their own skills. Receipt organization gives us a concrete, inspectable workload: the agent must read the guide, extract the purchase correctly and ignore instructions that do not belong to the receipt task.

## What it does
SkillGuard pauses native Hermes skill writes before activation and snapshots the proposed guide and script. NVIDIA SkillEvaluator checks the source and generates security probes. A real Harbor agent uses the proposed skill inside OpenShell while SkillGuard collects partial independent native observations, compares behavior and previews the sandbox policy. Nemotron reviews the saved evidence.

The operator sees a decision tied to the exact source and can approve, reject, test a known repair or restore a previous version. Failed or incomplete native checks and observed unsafe actions cannot be overridden by a favorable model response. If all native checks pass but the model holds, a separate acknowledged human exception requires a written reason and retains the warning.

The working profile is receipt organization in a fixed isolated workspace. It is not unrestricted agent activation, model-weight training or a general security guarantee. The known V8 repair is explicitly selected and retested; SkillGuard does not claim arbitrary autonomous code repair.

## How we built it
Nebius Token Factory serves NVIDIA Nemotron 3.5 Lightning (`nvidia/Nemotron-3_5-Lightning`) for probe generation, actual tool-using agent trials and evidence recommendations. One Nemotron 3 Super adjudication (`nvidia/nemotron-3-super-120b-a12b`) is available for a complete held verdict. Token Factory's OpenAI-compatible interface let us use the existing evaluator and agent with one inference service, without hosting model weights. We did not measure a speedup or onboarding-time improvement.

NVIDIA SkillEvaluator supplies native scanning, generation, task models and response parsing. Harbor supplies the Terminus agent and independent functional grading. OpenShell supplies confinement and policy admission; Sysdig supplies partial native file/process observations. SkillGuard adds interception, evidence/source binding, behavioral envelopes and differences, review decisions, policy compilation, explicit approval lineage and rollback.

The live backend runs independently of the Mac in a dedicated GitHub Codespace, with a separate Debian/OpenShell VM and no host-folder mounts. The Nebius key stays in private server-side configuration outside candidate sandboxes. GitHub Codespaces supplies hosting; we do not claim use of Nebius AI Cloud, Serverless Jobs or Token Factory Sandboxes. Sandbox entitlement on this account returned HTTP 403.

## What we verified
The cloud HTTPS acceptance completed security review, installation, actual installed-agent execution, unsafe-update rejection, known repair, rollback and restoration. All twelve authored native regression cases passed. Four initial security probes and four final repair probes completed correctly. A separate run of the restored installed version read its guide before and after receipt input, saved the correct 23.00 total and confirmed completion in six actual Nebius requests.

The new live recording repeated this lifecycle with four fresh probes using 23 agent requests and a separate seven-request installed-agent completion. Its final hold, explicit restricted installation and rollback are verified in `results/oct24-live-recording-verification.json`. The full offline suite now passes 1009 tests.

The initial cloud review returned a restricted allow. The final repair review returned **hold** and was installed through an explicit restricted human exception. That warning is preserved as `operator_approved_hold`, not relabeled as a model pass. Full proof and source hashes: `results/oct23-cloud-backend-verification.json`.

An earlier paired skill/no-skill study found no overall safe-completion gain: 7/8 in each arm after counting unsafe attempts as failures. A separate guide-repair comparison found 8/8 correct confirmed completions for V8 versus 2/8 for the original guide on eight new authored receipts. These are small studies under their original six-request bounds, not general detection rates. The deployment uses a distinct eight-request completion profile and does not inherit benchmark credit from those studies.

Every failed run and uncertain cost remains preserved. The app enforces per-trial request and output limits plus an aggregate authorization at the inference transport. Estimates are not provider billing totals. No latency or broad attack-resistance claim is made.

## Challenges and lessons
Correct output is not enough: an agent can attempt a forbidden read and still return the right answer. We therefore inspect recorded actions as well as functional grades. Native frontmatter discovery needed a narrow pinned compatibility wrapper. Generated ordinary questions were not adequate attacks, so we retained that failure and added explicit security framing and coverage validation. Cloud cold starts, provider latency and trace processing required declared prospective deadlines; old failed trials were never relabeled. Concurrent live page polling also exposed a snapshot-creation race, fixed with serialized capture and a regression test.

## What's next
Broader skill domains, independently curated attack sets, better native attribution and durable judging/production hosting. The frozen receipt-profile core is working; those broader claims remain outside scope.

## Built with
Python, JavaScript, Hermes Agent, NVIDIA SkillEvaluator, NVIDIA Nemotron 3.5 Lightning, NVIDIA Nemotron 3 Super, Nebius Token Factory, Harbor, OpenShell, Sysdig, Lima, Docker, GitHub Codespaces.
