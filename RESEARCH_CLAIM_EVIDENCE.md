# Verifiable research claim evidence v1

Status: **dormant migration contract**. Nothing in this slice enables BrowserHost, DNS, CDP, a provider, an API route or public-network access.

## Why a receipt is not enough

A `kaliv-data-sharing-receipt/v1` proves that one exact external-read request was authorized. Before `claim`, that receipt may still be revoked, expire or lose a one-use race. A peer-binding layer must therefore not accept an issued receipt as proof that external processing has started.

`kaliv-data-sharing-claim/v1` is minted atomically in the same SQLite transaction that changes the common receipt from `authorized` to `in_flight`. It binds:

- the exact common receipt ID;
- the exact request digest;
- the exact byte ceiling;
- the database claim timestamp;
- the receipt expiry.

## Verification

`VerifiableDataSharingLedger.verify_claim` checks the evidence against the current durable row. Verification succeeds only while the receipt is still `in_flight`, unexpired and identical on every bound field.

Completion, blocking, failure, expiry, a changed request, a forged timestamp or a changed byte ceiling invalidates the evidence. Reopening the same SQLite ledger preserves legitimate in-flight verification.

## Research boundary

`VerifiableResearchSharingBoundary` is a dormant subtype of the existing research boundary. It preserves the exact lease, request and policy checks, but returns the atomic claim evidence from `claim` and exposes read-only verification for a later peer-binding adapter.

## Privacy

The evidence contains no raw purpose, preview summary, content, URL or credentials. Existing common audit behavior remains hash-based.

## Next gate

A later common peer-binding slice may accept this evidence only after claim and bind it to one canonical URL, one DNS answer set and one connected public peer. BrowserHost/CDP activation and physical public-network validation remain separate blockers.
