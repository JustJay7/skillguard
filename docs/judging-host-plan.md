# Dedicated judging host: prepared, not deployed

The entrant requested the actual application through December 15, with no owner
restarts, no additional hosting bill, and the video kept local. The present
Codespace was confirmed `Shutdown` on October 24. Its included compute allowance
and idle shutdown prevent continuous unattended hosting. Do not run keepalive
jobs, reset quotas, or claim that the recorded Site solves live access.

## Current candidate: Azure Student offer active; region access blocked

The entrant completed academic verification on October 24. Education Hub now
shows the active year-long Student offer with credit expiring October 24, 2027.
The actual balance and subscription identifiers are retained privately in
`results/judging-host-preparation/azure-student-activation.json`. The separate
30-day trial is not the Student entitlement. No paid upgrade or removal of credit
spending protection is authorized. The final spending-protection and quota gate
must still pass before resource creation.

Central India `Standard_D2als_v6` is a non-Spot x86 machine with two CPUs, 4 GiB RAM
and documented nested virtualization. The prepared form uses Ubuntu 24.04 Gen2,
Standard security and NVMe. Microsoft's retail API lists Linux compute at
$0.052/hour, Standard IPv4 at $0.005/hour, and E6 LRS Standard SSD at $5.28/month.
A conservative 1,277-hour window through `2026-12-16T05:00:00Z` estimates $82.03 in
base resources plus $15 provisional usage reserve. The earlier HDD forecast was
$78.58 base; the SSD improves expected disk performance. Forecasts are not caps.
Disk operations, traffic, other account usage and expiry remain deployment gates.

Actual Azure deployment validation rejects Central India with
`InvalidTemplateDeployment / RequestDisallowedByAzure`. The subscription's
assigned allowed locations are France Central, Canada Central, Sweden Central,
Norway East and Denmark East. The known compatible machine rates there exceed
the student credit over the full window. The portal also marks B2als_v2 unavailable
in Canada Central and France Central and B2s unavailable in Canada Central.
Those smaller burstable sizes lack hardware nesting, so they are not accepted as
compatible replacements. No software emulation or relaxed execution limits were
deployed to turn an infrastructure failure into a pass.

Microsoft's official Azure CLI 2.91.0 is installed in private task tooling with
telemetry disabled. McGill conditional access rejected the sign-in; it was stopped
without an alternate authentication attempt or policy change. Continue only via
the permitted signed-in portal. Do not bypass school restrictions.

The entrant explicitly authorized the account-specific support message and then
accepted the final submission terms. The Basic subscription-management case was
submitted and verified **Open**, with Microsoft acknowledgement. The case ID,
exact payload and confirmation screenshot remain private under
`results/judging-host-preparation/`. Contact is email, severity C/business hours;
no advanced diagnostic permission or paid support plan was granted. Microsoft
must now decide the region entitlement or identify a compatible alternative;
no response deadline is promised. Billing/subscription support is included.

No VM, network resource, hosting charge, credential transfer or model request
has occurred in this migration. The prepared form and local units do not establish
native compatibility or unattended availability. Do not publish a new judging
URL or replace the prior verified release until deployment acceptance passes.

## Rejected candidate: Google Cloud Free Trial

Use a separate Google Cloud Free Trial project, only if this account is eligible
and its actual credit balance and expiry cover the complete judging window.
Google documents $300 over 90 days, with no charges while the account remains a
Free Trial. Signup requires the entrant's identity/payment verification and may
place a temporary payment authorization hold. Do not upgrade to paid billing.

Proposed resources: one non-Spot `n1-standard-2` x86 VM in a US region (2 vCPU,
7.5 GiB RAM), a 60 GiB standard persistent boot disk, one stable external address,
and nested virtualization enabled on an Intel Haswell-or-newer CPU platform.
Confirm regional availability, live prices, quota and the account's trial status
before creation. Include disk, IP and traffic in a forecast through
`2026-12-16T05:00:00Z` (end of December 15 in Toronto), with headroom. An estimate
is not a spending cap. Trial expiry/credit exhaustion stop service; they must
fall beyond the access window. The always-free E2 VM does not support the
required nested virtualization.

Use a dedicated Linux user `skillguard`, persistent membership in the `kvm`
group, the existing `/workspaces/skillguard` and `/workspaces/work` layout, and
the pinned native runtime configuration. No instance service-account token is
needed by the application. Keep the app listening on loopback and put a TLS
reverse proxy on ports 80/443; preserve the original Host and Origin headers.
Restrict SSH to the operator/IAP rather than opening it to the internet. A final
stable hostname and certificate must be independently checked after creation.

## Prepared local changes

- `linux_vm` hosting mode labels the dedicated host without claiming uptime;
  authentication, CSRF, action restrictions and HTTPS-origin checks stay intact.
  The Codespaces-only rewritten-header exception is not enabled in this mode.
- `config/judging/skillguard.service` starts on boot, runs as the dedicated user,
  and restarts after process failure. Restart attempts are bounded. It is not an
  automatic retry mechanism for failed or unfinished model trials.
- `scripts/judging_health.py` checks only loopback `/health`, ignores proxy
  environment variables, and verifies the protected dedicated-host mode. It
  creates no session and submits no provider/model/action request.
- The health timer can recover the app process after a failed listener check.
  All service units require an explicit dedicated-host marker; do not install
  them in Codespaces to evade its idle limits.
- The expiry timer powers off the marked VM after the access window. This ends
  compute use, not retained-disk/address storage; final resource cleanup remains
  an explicit later action. No paid billing upgrade is allowed.

Linux `systemd-analyze verify` accepts all six unit files without warnings in the
existing development workspace; no service was installed or started there.
These unit files have not yet been installed or exercised under systemd on the
proposed host. Local HTTP tests do not establish cloud uptime or compatibility.

## Required deployment acceptance

1. Confirm trial/non-paid status, real remaining credit, expiry, exact regional
   price forecast and quota. Create only the dedicated project/resources.
2. Provision the pinned native runtime. Verify KVM and guest isolation, no host
   mounts, no forwarded credentials, native tracing and collector completion.
3. Quiesce the old paid-action service before migration. Transfer the private
   provider configuration, complete authoritative ledger, spending authorization,
   review/install state and required bound evidence through authenticated
   encrypted transport. Preserve every prior row and unknown hold; never create
   a second inference authority. Keep private data out of public Git and logs.
4. Verify active candidate/review/version hashes and historical results. Refresh
   only deployment-specific checks; retain all previous failures and holds.
5. Independently verify public HTTPS, anonymous refusal, authenticated current
   state, origin/CSRF enforcement, safe secret-path handling and the actual native
   flow within the existing inference authorization.
6. Install the bounded startup/recovery/expiry services only after verifying
   systemd configuration. Kill the app process and reboot the dedicated host;
   independently verify automatic recovery and unchanged active state/accounting.
   Do not repeat any consumed paid trial just to recover an observer.
7. Update judging instructions and the sanitized source/packet with the verified
   stable URL. Keep both videos local. Do not submit an entry or publish video.

## Verified documentation

- [Azure subscription support](https://learn.microsoft.com/azure/azure-supportability/how-to-create-azure-support-request)
- [Azure student offer](https://azure.microsoft.com/en-us/free/students/)
- [Azure student credit expiry and shutdown](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/azurestudents-subscription-disabled)
- [Dalsv6 hardware and nesting support](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/dalsv6-series)
- [Azure retail price API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
- [Azure credit balance inspection](https://learn.microsoft.com/en-us/azure/cost-management-billing/benefits/credits/mca-check-azure-credits-balance)
- [GitHub included usage](https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-included-usage)
- [Google Cloud Free Trial](https://docs.cloud.google.com/free/docs/free-cloud-features)
- [Nested virtualization restrictions](https://docs.cloud.google.com/compute/docs/instances/nested-virtualization/overview)
- [Enable nested virtualization](https://docs.cloud.google.com/compute/docs/instances/nested-virtualization/enabling)
- [External IP pricing](https://cloud.google.com/vpc/pricing)

In the earlier Google inspection, the account showed no active billing account. The Free Trial URL then
opened an overdue mandatory identity-verification notice. The entrant selected
"I'll activate the free trial" but subsequently confirmed no trial is offered.
That route is closed; do not request further verification for this project.

The final visual check also shows **Paid account** behind that notice. The
existing account is not a verified non-billable trial. Do not deploy into it on
the assumption that signup/verification supplies new credit. The entrant was
informed before any resource creation and asked whether a genuinely new trial
is offered, or whether another existing host/credit entitlement is available.
Do not ask the entrant to create another identity or add funds.

Current Azure check: Student activation is complete, but region validation and
smaller-size checks exposed an account entitlement blocker. No birth date or
identity document was supplied by the agent. Private activation/error records
remain outside the public release. The authorized Basic support case is open and awaiting Microsoft
response; the exact request and tracking details remain private.

Local dedicated-host HTTP/health checks: 25 passed; Ruff and whitespace clean.
No new VM, billing upgrade, API-key transfer or model call has been performed for
this migration. The actual-live video remains local and byte-identical.
