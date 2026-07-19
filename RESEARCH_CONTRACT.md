# Web research contract v1

**Status:** contract, deterministic fetch engine, pinned transport, isolated BrowserHost, dormant Browser Use adapter, installed-runtime contract, controlled local-Chromium gate and dormant egress ledger delivered; no ToolGate activation or public-network validation yet.

This contract keeps Browser Use, Playwright and plain HTTP interchangeable. ModelRig owns the safety and evidence model; an adapter only performs retrieval and proposes citations.

## Boundary

`worker/app/research_contract.py` defines:

- `ResearchRequest` — query, source budget and a mandatory read-only policy;
- `ReadOnlyBrowserPolicy` — explicit exact/wildcard domain allowlist, ephemeral profile, bounded pages/steps/bytes/time, and hard denial of credentials, login, uploads and downloads;
- `SourceReceipt` — canonical URL, retrieval timestamp, byte count, content SHA-256, bounded excerpt and deterministic source id;
- `Citation` — one numbered answer marker tied to one or more receipts;
- `ResearchResult` — an answer that must contain every declared citation marker and may only cite included receipts.

`worker/app/web_fetch.py` implements deterministic navigation, redirect handling, content limits and receipts. `worker/app/pinned_http_transport.py` implements one dormant production transport behind the existing `FetchTransport` seam. `worker/app/browser_host.py` defines the one-request process boundary. `worker/app/browser_use_adapter.py` is an optional, lazy-loaded Browser Use backend. `worker/app/browser_use_network_guard.py` owns the Chromium request boundary. `worker/app/research_egress.py` owns the dormant one-use consent, authorization receipt and hash-only audit state machine. Nothing is registered in ToolGate or exposed through an API route.

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

## BrowserHost process invariants

The dormant BrowserHost:

- accepts exactly one bounded UTF-8 JSON request and emits exactly one bounded JSON response;
- requires every policy field explicitly and rejects unknown fields, persistent profiles, credentials, login, upload and download access;
- runs one injected backend under the research wall-clock deadline and always attempts bounded cleanup;
- validates step, page, source and byte budgets after execution;
- requires every source URL to be both allowlisted and present in the canonical visit trace;
- receives bounded evidence artifacts and citation indexes, then creates the final source ids and citations itself;
- normalizes backend, timeout, contract and cleanup failures without returning raw exception details;
- defaults to a typed `backend_unavailable` result unless a backend is explicitly supplied.

## Browser Use adapter invariants

The optional adapter:

- lives in its own exact-pinned runtime environment and is never installed by the base worker requirements; Browser Use 0.13.4 and the worker intentionally pin different Pydantic versions, so combining the environments is rejected by dependency resolution;
- loads Browser Use lazily and fails closed on a missing version, unexpected version or incompatible Agent, BrowserProfile or Tools surface;
- disables Browser Use telemetry, cloud sync, version checks and package logging setup before importing the runtime;
- constructs an ephemeral headless profile with explicit domains, no imported storage state, no proxy or proxy credentials, blocked direct-IP navigation, no default extensions, downloads refused at browser-context level, zero browser permissions, no automatic PDF downloads, no cross-origin iframe traversal and no captcha solver;
- restores Chromium's popup blocker, which Browser Use disables by default;
- removes search-engine navigation, generic clicking, form input, uploads, keyboard injection, arbitrary JavaScript evaluation, dropdown selection, PDF creation, screenshots, tab switching/closing and file read/write actions from the registry;
- replaces Browser Use's navigation model with a current-tab-only schema where `new_tab=true` is structurally invalid;
- installs a `Fetch.requestPaused` interceptor before `Agent.run`; each HTTP(S) request must be explicitly continued by ModelRig or is failed in Chromium with `BlockedByClient`;
- rejects URL credentials, numeric IP literals, localhost/internal suffixes and any exact/wildcard domain outside the request allowlist at the CDP request boundary;
- treats Browser Use's own navigation watchdog as defence in depth only: controlled Chromium testing proved its event-level rejection can race with the navigation handler and reach the network before the error is observed;
- bounds tracked request ids, in-flight CDP responses, error codes and blocked-URL evidence so a hostile page cannot turn the guard into unbounded memory growth;
- supplies no credentials, sensitive data or upload paths and allows one action per bounded step;
- adopts Browser Use's generated `browser-use-downloads-*` and `browser-use-user-data-dir-*` system-temp directories as quarantines;
- rejects any file written to the download quarantine, keeps request interception active while the browser closes, then disables the guard and deletes both download and browser-profile quarantines;
- requires structured answers with numeric citations and exact supporting URLs;
- rejects non-web, non-allowlisted, unvisited or over-budget history and citation URLs;
- re-fetches every unique cited URL through ModelRig's deterministic pinned fetcher;
- converts the trusted fetch receipt into a canonical verified-source envelope containing the original content SHA-256, byte count, URL, media type, timestamp and adapter provenance;
- never permits Browser Use to create ModelRig source hashes, source ids or final citations.

The dedicated `browser-use-runtime-contract` CI job installs `browser-use[core]==0.13.4` in isolation and validates the real imports, Agent and Tools signatures, locked BrowserProfile fields, current-tab-only navigation schema, generated download/profile temp directories, disabled side channels, history interface and concrete action registry. It then launches real headless Chromium, visits one controlled `localhost` fixture through the same CDP request guard used by the adapter, verifies its title, proves an external domain and numeric loopback URL are failed before either reaches the fixture server, confirms the download quarantine remains empty and proves cleanup. It creates no LLM client and performs no public-site research. On failure it publishes a short seven-day diagnostic artifact; successful runs publish nothing.

## Egress authorization invariants

The dormant egress ledger:

- binds the exact destination, purpose digest, outbound payload digest, sensitivity, domain scope and byte ceiling into one canonical plan digest;
- keeps the human-readable purpose in the confirmation payload but never writes raw purpose or payload content to the audit database;
- reuses the existing sensitivity rule: public and operational plans may authorize automatically, private plans require an exact approved consent, and secret plans are always refused;
- makes consent short-lived and one-use, so approval for one payload, purpose, domain set or byte ceiling cannot authorize another;
- issues a separate short-lived receipt that must be atomically claimed exactly once at the eventual network boundary;
- records completion, bounded byte count and normalized error code only after a claimed receipt is in flight;
- persists proposals, receipts and append-only hash-only audit events in SQLite across process restarts;
- performs no network call and is not wired to BrowserHost, ToolGate or an API route in this slice.

## Remaining obligations

Before activation:

1. bind Browser Use's public-domain requests to validated public DNS answers/peers and run live-network validation against controlled public fixtures; the local launch and domain/IP request-boundary gates are delivered;
2. wire the delivered egress ledger into BrowserHost confirmation, CDP request claiming/completion and the user-visible audit trail;
3. expose the capability through a canonical descriptor and ToolGate only after those gates are green;
4. keep authentication, cookies, uploads and downloads outside v1.

## Planned slices

1. **T-034A — contract**: delivered in 1.58.111.
2. **T-034C1 — deterministic `web_fetch` engine + fake transport tests**: delivered in 1.58.112.
3. **T-034C2 — production pinned HTTP transport**: delivered in 1.58.114; dormant and socket/TLS-tested, not live-network validated.
4. **T-034B — isolated BrowserHost + fixture backend**: delivered in 1.58.115.
5. **T-034D1 — dormant Browser Use adapter**: delivered in 1.58.119; exact pin, fake-runtime tests and deterministic citation re-fetch.
6. **T-034D2 — installed runtime contract**: delivered; real 0.13.4 package surface, dependency isolation, locked profile, action registry and side-channel controls.
7. **T-034D3 — controlled Chromium request-boundary gate**: delivered in 1.58.123; real browser startup, current-tab-only tools, CDP domain/IP denial and cleanup without an LLM or public network.
8. **T-034E1 — dormant egress authorization ledger**: this delivery; exact-plan consent, one-use receipts and hash-only audit without runtime wiring.
9. **T-034E2 — runtime integration**: public-peer binding, BrowserHost consent/audit wiring, CapabilityDescriptor, public-network validation and eval gates.

Authenticated browsing is a separate future capability, not a flag added to this contract.
