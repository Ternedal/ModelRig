# Data-sharing policy v1

Status: **dormant contract and migration boundaries**. These modules do not enable any route, connector, tool or network client.

## Decision

The first common policy for Agent v2, Agent 3, research and future connectors is:

| Data category | External read processing |
|---|---|
| `public` | Automatic, but still request-bound and receipted |
| `operational` | Exact, short-lived, one-use user permission |
| `private` | Exact, short-lived, one-use user permission |
| `secret` | Forbidden, including with permission |

The policy schema is `kaliv-data-sharing-policy/v1`.

## Request and preview

Every external-read attempt must build one canonical `kaliv-data-sharing-request/v1` request before any bytes leave the machine. Its digest binds:

- originating surface (`agent_v2`, `agent3`, `research` or `connector`);
- destination type, provider and stable logical destination;
- data category;
- purpose code and hash of the full purpose;
- hash of the limited human preview summary;
- hash and maximum byte count of the content.

The confirmation preview may show the plain purpose and a summary of at most 180 characters. It must never include the full shared content, credentials, tokens or query parameters.

## Permission and receipt lifecycle

A confirmation-required request creates a `kaliv-data-sharing-permission/v1` proposal. Permission is:

- scoped to the exact request digest;
- time-limited;
- one-use;
- explicitly approvable, deniable and revocable;
- consumed atomically when a receipt is issued;
- still revocable until the issued receipt is claimed; revocation atomically invalidates every unclaimed receipt linked to it.

External processing requires a claimable `kaliv-data-sharing-receipt/v1`. Receipts are short-lived, exact-request-bound, one-use at the boundary and terminal after completion. Once claimed, revocation cannot pretend that already-started external processing never happened.

Changing provider, destination, content, purpose, summary, surface or byte budget creates a different digest and therefore requires a new decision.

## Audit and privacy

The append-only audit records what category moved, why at the purpose-code level, where it was intended to go, under which permission/receipt and the terminal outcome.

It stores hashes of purpose, summary and content—not the raw purpose, preview summary or shared content. Logs and telemetry must not copy the payload.

Denial, timeout, revocation, mismatch and reuse produce no valid receipt. Local fallback is recorded with `bytes_sent=0`.

## Research migration boundaries

`worker/app/research_data_sharing.py` translates the legacy research `EgressPlan` into the common request. The normalized domain allowlist is included through a full SHA-256 scope digest, so a wider or simply different domain set requires a new decision.

`worker/app/research_sharing_boundary.py` defines the dormant execution lease around the eventual external operation:

- `observe` reports legacy/common policy differences but is side-effect free, contains no receipt and can never authorize bytes;
- `enforce` must issue and claim an exact common receipt before the real external-processing boundary;
- every lease binds the legacy plan digest, common request digest and active policy digest;
- rollback from `enforce` to `observe` cannot claim or reuse an enforced lease;
- the caller must report the measured external byte count and real terminal outcome; the boundary never guesses either value.

The intentional migration delta is explicit: legacy research allowed `operational` data automatically, while common v1 requires permission.

## Integration gate

No surface may call an external read service directly. Agent v2, Agent 3, research and connectors must all cross this module or a later compatible version.

The delivered research adapter and lease boundary are not imported by BrowserHost, ToolGate or an API route. BrowserHost/CDP wiring, public-peer pinning and controlled public-network validation remain separate activation blockers.
