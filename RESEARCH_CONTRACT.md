# Web research contract v1

**Status:** isolated foundation; no browser adapter or runtime registration yet.

This contract keeps BrowserUse, Playwright and plain HTTP interchangeable. ModelRig owns the safety and evidence model; an adapter only performs retrieval.

## Boundary

`worker/app/research_contract.py` defines:

- `ResearchRequest` — query, source budget and a mandatory read-only policy;
- `ReadOnlyBrowserPolicy` — explicit exact/wildcard domain allowlist, ephemeral profile, bounded pages/steps/bytes/time, and hard denial of credentials, login, uploads and downloads;
- `SourceReceipt` — canonical URL, retrieval timestamp, byte count, content SHA-256, bounded excerpt and deterministic source id;
- `Citation` — one numbered answer marker tied to one or more receipts;
- `ResearchResult` — an answer that must contain every declared citation marker and may only cite included receipts.

The module performs no network calls, imports no browser framework and is not registered in ToolGate. Existing runtime behaviour is unchanged.

## Adapter obligations

A future adapter must:

1. call `policy.require_allowed_url()` before every navigation or fetch;
2. resolve the host itself and call `policy.require_public_address()` on every DNS answer before connecting and after redirects;
3. use a fresh ephemeral browser profile with no imported cookies or credentials;
4. enforce the policy budgets outside the model prompt;
5. build receipts from the actual fetched bytes, not model-written summaries;
6. return citations that reference those receipts;
7. keep downloads, uploads and authentication out of v1;
8. remain unregistered until egress receipts and audit integration are ready.

## Planned slices

1. **T-034A — contract**: this delivery.
2. **T-034B — fixture BrowserHost**: separate process, local fixture sites, fake planner, no ToolGate registration.
3. **T-034C — `web_fetch` adapter**: deterministic HTTP retrieval before agentic browsing.
4. **T-034D — BrowserUse fallback**: JavaScript/navigation only, same contract.
5. **T-034E — runtime integration**: CapabilityDescriptor, egress receipt, audit and eval gates.

Authenticated browsing is a separate future capability, not a flag added to this contract.
