# Public execution backend

The protected entry serves the actual SkillGuard application. Its independent fictional
workspace can stage a skill, run the real native security review, install after a
passing decision or explicit held-verdict acceptance, run the installed agent, reject
an unsafe update and roll back versions. It is not the recorded Site walkthrough.

The server keeps the Nebius key in its private ignored `.env`. The browser receives
neither that key nor arbitrary host-file access. A separate random access code protects
credit-consuming and installation actions. All visitors with that code share operator
access to the fictional workspace; this is a supervised demonstration, not a multi-user
service. Do not submit personal receipts. Reviews retain source bindings, native checks,
held verdicts, irreversible failure history and the aggregate spending ledger.

## Free development hosting

The deployment investigation uses the account's included GitHub Codespaces allowance
with its existing $0 Codespaces spending limit. Codespaces is a development environment:
idle suspension, included compute/storage limits and eventual retention deletion apply.
It is not an always-on production hosting promise. Keep the workspace running for a
scheduled judge session. Do not raise the spending limit or add billing to extend it.

`config/linux-cloud-trace.yaml` provisions a separate x86 Debian VM using Lima 2.2.0
and QEMU. It has no host-folder mounts or forwarded provider environment. Official
image/OpenShell/Sysdig downloads have pinned checksums. The VM contains Docker,
OpenShell 0.1.2, Harbor 0.13.2 and Sysdig 0.41.4. The app/controller environment stays
outside the candidate sandbox. `scripts/setup_cloud_host.sh` installs the existing
pinned upstream sources and app dependencies on a dedicated Linux host; it does not
supply credentials, start a public server or run model inference.

Run the public entry only after native controls have passed on the new host:

```sh
export PATH="/workspaces/work/lima/bin:/workspaces/work/semgrep-venv/bin:/workspaces/work/skillspector-venv/bin:/workspaces/work/bin:/workspaces/skillguard/.venv/bin:$PATH"
.venv/bin/python -m skillguard.ui.public_server \
  --origin-file results/public-hosting/origin.txt \
  --access-file results/public-hosting/access-code.txt --hosting-mode codespaces
```

The exact forwarded HTTPS origin must be stored in `origin.txt`. The access code must
be at least 32 characters, in a regular file readable only by the operator. The backend
binds to loopback, requires the exact Host/Origin, authenticates sessions with Secure,
HttpOnly, SameSite cookies, and requires CSRF protection for mutations. GitHub rewrites
the upstream Host and Origin: cloud mode accepts that mapping only from loopback with
the exact forwarded HTTPS host and the same-origin script marker. It grants no CORS
preflight; a cross-origin browser cannot add that marker. Arbitrary skill
imports and the local parser utility are excluded from the public action allowlist.
The `codespaces` mode labels cloud location and idle/quota limits; it does not itself
prove native execution. Retain a fresh native preflight and real HTTP acceptance result.

Preserve the original private workspace. When moving execution, stop the old paid-action
servers before transferring the complete cost ledger and authorization. Use one active
inference authority, retain unknown holds and never reset completed or failed claims.

## Temporary Mac endpoint

`make public-live` runs the same protected application through a free Cloudflare Quick
Tunnel. This mode requires the Mac, network and tunnel process to remain running. Its
random hostname can change or disappear; no uptime guarantee is implied. One earlier
hostname disappeared during read-only observation; the native action continued and its
failure record was preserved. A replacement hostname does not repeat model actions.

The launcher expects the official macOS ARM cloudflared 2026.10.3 binary at
`../work/cloudflared-2026.10.3/cloudflared`. Obtain it from the official
[Cloudflare release](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.3).
The archive `cloudflared-darwin-arm64.tgz` must have SHA-256
`1165d14b6f6360a3b8c283d7d1100024d6ec7cd9bc9e32519e96150645f3ec55`.
The launcher refuses an already running public server and prints the access-code file
location instead of its contents. Hosting secrets, logs and runtime stores are ignored
and excluded from source releases. Never put the code in a URL or public README.

## Verification and retained failures

`python -m scripts.public_backend_check` exercises the public HTTPS actions with the
real native runtime and bounded model calls. It refuses an existing run record. Its
explicit observation continuation never repeats a model action, including after a
client-side observation timeout. The observer allows two hours for the bounded native
preflight/live sequence; each individual native worker retains its own timeout. Its separate validation
continuation preserves the first failure and reuses the exact paid test-generation
response after a fixture-wording correction; earlier passed agent trials are retained.
Neither continuation counts as a fresh independent attack benchmark.

A correct native result does not erase a model hold. Installation with a held verdict
records the explicit reason and `operator_approved_hold`; unsafe or incomplete native
evidence remains blocked. Provider billing totals may differ from token-based estimates.

The packaged fixed agent task is an uncompressed, hash-checked source archive under
`config/`. Its materializer verifies every file and refuses symlinks/traversal; it creates
only disabled template proposals. Authenticated app actions create the separate enabled,
source-bound proposals with fresh claims. This removes dependence on private development
history. The embedded NVIDIA SkillEvaluator scaffold retains Apache-2.0 SPDX notices;
its license is in `docs/third-party-notices/SkillEvaluator-LICENSE`. SkillGuard's original
application code remains MIT-licensed. Existing development proposals are not rewritten.

App trials require current candidate-bound native/static checks and an exact captured
fake-key preflight on the executing host. Legacy standalone research trials retain their
additional historical recorded-replay prerequisite. A copied historical result cannot
satisfy the app's fresh preflight, and no model request is made by template creation.

The first independent cloud review retained a real completion failure: all four files
were correct with no observed unsafe actions, but one agent exhausted six requests
before native confirmation. New app proposals use the explicit eight-request completion
profile; old six-request proposals, claims and comparison metrics remain unchanged.
The one profile transition records the previous review/hash and exposes that history to
the evidence reviewer. Native failure/unsafe actions still block installation. This is
a prospective execution-bound change, not a new skill repair or blind benchmark.

A Codespace resume can clear its forwarded port. Register port 8770 using the documented
GitHub CLI port-forward command, restore its public visibility, then close that temporary
local registration connection. Verify `/health` over the public URL afterward: the cloud
app must remain reachable with `depends_on_mac=false`. Port registration does not turn
the Mac into the backend. The operator's private launcher performs these checks.
