# Tavily threat research in SkillGuard

The authenticated application now provides **Research attack coverage · Tavily**.
This makes a real Tavily Search API call using a fixed public prompt-injection query
and an allowlist of OWASP and NVIDIA documentation domains. It sends no skill source,
receipt, private note, API key from another provider, or runtime trace to Tavily.

The operator sees cited references and a receipt-test coverage checklist. Retrieved
snippets are classified into four fixed categories: private-file access, receipt-total
poisoning, role spoofing and off-task diversion. When a future native security review
builds its generation guidance, SkillGuard adds those category names and retains the
research evidence beside that review. Raw web instructions never enter the generation
prompt and cannot grant permissions, change the native gate, or approve installation.

One basic search is used per refresh, with a ten-minute cache, at most four references,
no generated answer, and no automatic switch to a more expensive search depth. The
saved response includes Tavily's reported credit usage and request identifier.
The key belongs in the server's ignored `.env` as `TAVILY_API_KEY`.

The first verified local request used **one Tavily credit**, returned three OWASP
references and populated all four categories. A separate authenticated cloud HTTP
check records its own actual response in `results/oct30-tavily-runtime-verification.json`.
Existing native reviews and the uploaded video predate this addition; their outcomes
are preserved. This addition does not claim a new Tavily-informed native agent trial.

API implementation follows the [official Tavily Search reference](https://docs.tavily.com/documentation/api-reference/endpoint/search).
