# SkillGuard source release

This archive contains source, tests, documentation and an inspectable recorded demo.
It excludes Git history, .env, private runtime stores, raw captures and VM images.
The installed local application and its runtime are not exported.

For the recorded walkthrough, no key or dependencies are needed:
python3 -m http.server 8769 --bind 127.0.0.1 --directory recorded-demo
Open http://127.0.0.1:8769/ . This is replay, not live inference or installation.

For native execution, use Python 3.12+ and the pinned Hermes/SkillEvaluator sources
and Linux OpenShell stack documented in README.md, docs/upstream-pins.json,
config/linux-trace.yaml and docs/core-flow.md. make setup installs Python app
dependencies only; it does not provision the native VM. Credentials belong only
in a local ignored .env. Archived live proposals are not fresh authorizations.

Exported JSON summaries may redact workspace paths and are labeled accordingly.
Retained native proofs belong to the original run, not this source export.
