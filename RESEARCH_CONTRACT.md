# Web research contract v1

**Status:** contract, deterministic fetch engine and pinned stdlib transport delivered; no runtime registration, browser framework or live-network validation yet.

This contract keeps BrowserUse, Playwright and plain HTTP interchangeable. ModelRig owns the safety and evidence model; an adapter only performs retrieval.

## Boundary

`worker/app/research_contract.py` defines:

- `ResearchRequest` — query, source budget and a mandatory read-only policy;
- `ReadOnlyBrowserPolicy` — explicit exact/wildcard domain allowlist, ephemeral profile, bounded pages/steps/bytes/time, and hard denial of credentials, login, uploads and downloads;
- `SourceReceipt` — canonical URL, retrieval timestamp, byte count, content SHA-256, bounded excerpt and deterministic source id;
- `Citation` — one numbered answer marker tied to one or more receipts;
- `ResearchResult` — an answer that must contain every declared citation marker and may only cite included receipts.

`worker/app/web_fetch.py` implements deterministic navigation, redirect handling, content limits and receipts. `worker/app/pinned_http_transport.py` implements one dormant production transport behind the existing `FetchTransport` seam. Nothing is registered in ToolGate or exposed through an API route.

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

## Pinned transport invariants

The stdlib transport:

- bypasses proxy/environment discovery and performs no hostname resolution;
- opens one numeric IPv4/IPv6 socket to the exact `connect_address` selected by the engine;
- preserves the canonical URL hostname for HTTP `Host`, TLS SNI and certificate verification;
- returns redirects to the engine instead of following them;
- rejects caller-supplied credentials, hop-by-hop headers and header injection;
- rejects ambiguous response framing such as duplicate singleton headers or mixed `Content-Length`/`Transfer-Encoding`;
- reads transfer-decoded body bytes incrementally and stops at `max_wire_bytes`;
- closes sockets and normalizes TLS, timeout, parser and connection failures without leaking private exception details.

## Remaining adapter obligations

Before activation:

1. run explicit live-network validation against controlled public fixtures;
2. add egress consent/receipt and audit integration;
3. expose the capability through a canonical descriptor and ToolGate only after those gates are green;
4. keep authentication, cookies, uploads and downloads outside v1.

## Planned slices

1. **T-034A — contract**: delivered in 1.58.111.
2. **T-034C1 — deterministic `web_fetch` engine + fake transport tests**: delivered in 1.58.112.
3. **T-034C2 — production pinned HTTP transport**: this delivery; dormant and socket/TLS-tested, not live-network validated.
4. **T-034B — fixture BrowserHost**: separate process, local fixture sites, fake planner, no ToolGate registration.
5. **T-034D — BrowserUse fallback**: JavaScript/navigation only, same contract.
6. **T-034E — runtime integration**: CapabilityDescriptor, egress receipt, audit and eval gates.

Authenticated browsing is a separate future capability, not a flag added to this contract.
