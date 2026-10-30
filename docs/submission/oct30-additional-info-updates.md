# Final additional-info updates

## Did you use Tavily?

Yes. SkillGuard's authenticated runtime now calls Tavily Search to retrieve external
prompt-injection references. It displays cited OWASP sources, derives a bounded
receipt-test coverage checklist, and includes those categories in future probe-generation
guidance. We verified a real call through the cloud application's HTTP action, using
one Tavily credit. Retrieved text cannot authorize actions or approve installation.
The uploaded demo video predates this addition; runtime proof and source are in the repository.

## Comparison with other models

We ran the same eight fixed text-only receipt and evidence-review cases once each
against Nemotron 3.5 Lightning and Qwen3-30B-A3B-Instruct-2507 through Nebius Token
Factory. Both scored 7/8, with 3/4 extraction cases and 4/4 review cases correct. Both
followed the same forged correction and returned a zero total instead of 23. We
retained all outputs without retries. This small comparison gives no overall winner
and is separate from our native Harbor/OpenShell agent trials. The 16 calls cost an
estimated $0.00033512 at the configured token rates; these are not provider invoices.

## Model list addition

We also used Qwen/Qwen3-30B-A3B-Instruct-2507 as a low-cost comparison baseline on
the same hosted API. It is not the default SkillGuard execution or review model.

## Fine-tuning correction

We did not fine-tune model weights. We used prompt engineering and revised the
reusable receipt skill guide. Select or describe prompt engineering, not fine-tuning.

## Uploaded source attachment

Replace the earlier source ZIP with the newly rebuilt skillguard-source.zip. The
GitHub main branch and its downloadable source/test build include these additions.
