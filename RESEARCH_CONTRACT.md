# Web research contract v1

**Status:** contract + deterministic fetch engine delivered; no live transport, browser framework or runtime registration yet.

This contract keeps BrowserUse, Playwright and plain HTTP interchangeable. ModelRig owns the safety and evidence model; an adapter only performs retrieval.

## Boundary

`worker/app/research_contract.py` defines:

- `ResearchRequest` — query, source budget and a mandatory read-only policy;
- `ReadOnlyBrowserPolicy` — explicit exact/wildcard domain allowlist, ephemeral profile, bounded pages/steps/bytes/time, and hard denial of credentials, login, uploads and downloads;
- `SourceReceipt` — canonical URL, retrieval timestamp, byte count, content SHA-256, bounded excerpt and deterministic source id;
- `Citation` — one numbered answer marker tied to one or more receipts;
- `ResearchResult` — an answer that must contain every declared citation marker and may only cite included receipts.

`worker/app/web_fetch.py` now implements the deterministic retrieval engine under that contract. Network access remains injected through `FetchTransport`; main contains no production transport and the engine is not registered in ToolGate.

## Deterministic fetch invariants

The engine:

- validates every initial and redirected URL against the explicit allowlist;
- validates every DNS answer and fails the whole resolution if any answer is non-public;
- selects a deterministic address and requires the transport to prove that exact peer was used;
- refuses HTTPS downgrade, redirect loops, missing redirect targets and exhausted step/deadline budgets;
- sends only fixed read-only headers and never accepts caller-provided cookies or authorization;
- rejects attachments, binary media, unsupported encodings and non-200 terminal responses;
- enforces both wire-byte and decoded-byte caps with bounded streaming decompression;
- extracts bounded readable text and builds the receipt from the decoded entity bytes actually used.

## Adapter obligations

A production transport must:

1. never follow redirects itself;
2. connect to the exact `connect_address` supplied by the engine while preserving the URL host for TLS SNI and certificate validation;
3. return the actual connected peer address;
4. stop reading after `max_wire_bytes`;
5. apply the supplied timeout without importing cookies, credentials or proxy authentication;
6. remain unregistered until egress receipts and audit integration are ready.

## Planned slices

1. **T-034A — contract**: delivered in 1.58.111.
2. **T-034C1 — deterministic `web_fetch` engine + fake transport tests**: this delivery.
3. **T-034C2 — production pinned HTTP transport**: live-network validation, still dormant.
4. **T-034B — fixture BrowserHost**: separate process, local fixture sites, fake planner, no ToolGate registration.
5. **T-034D — BrowserUse fallback**: JavaScript/navigation only, same contract.
6. **T-034E — runtime integration**: CapabilityDescriptor, egress receipt, audit and eval gates.

Authenticated browsing is a separate future capability, not a flag added to this contract.
