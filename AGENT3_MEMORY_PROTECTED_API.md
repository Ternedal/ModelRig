# Agent 3 protected memory API boundary

**Status:** CONDITIONALLY SELECTABLE — default remains `legacy`; `protected`
requires exact gateway and store configuration and fails closed.

This boundary operates on a completed T-033 protected memory store without
turning storage access enums into authentication. It is mounted by the
production entrypoint only when both backend and worker are explicitly started
with `KALIV_AGENT3_MEMORY_STORE=protected`.

## Store selection

`KALIV_AGENT3_MEMORY_STORE` accepts exactly:

- empty or `legacy`: the historical plaintext `MemoryStore`, legacy CRUD/context
  routes and planner memory remain unchanged;
- `protected`: the protected reader/writer/API and bounded local planner-context
  provider are selected, while the legacy store, legacy context-preview and
  plaintext planner-memory integration are not mounted.

Protected startup requires all of the following before its route is included:

- a completed, internally consistent migration receipt for the selected DB;
- a provider/key-scope matching every protected envelope (Windows production:
  DPAPI current-user);
- `KALIV_AGENT3_MEMORY_API_SECRET` containing 32–4096 bytes;
- a canonical, non-symlinked `KALIV_AGENT3_MEMORY_GRANT_DB` path for the separate
  hash-only write-grant ledger.

Unknown modes, missing/short secrets, incomplete migrations, wrong providers,
wrong key scopes or an invalid replay-ledger path abort the mount. There is no
automatic migration and no protected-to-legacy fallback.

## Gateway authorization contract

The Bearer-authenticated Go gateway derives the paired device from `authMW` and
mints a 30-second HMAC-SHA256 grant only for a loopback worker. The grant is
domain-separated and binds:

- schema `kaliv-agent3-memory-grant/v1`;
- a random 256-bit nonce;
- authenticated device id;
- exact typed action (`status`, `read_metadata`, or `write_private`);
- exact `X-Request-ID`;
- exact HTTP method and worker path;
- exact raw query string;
- SHA-256 of the actual bounded request body;
- issue and expiry timestamps.

The protected body boundary is 64 KiB. The backend reads and hashes the exact
body, restores it for forwarding and rejects an oversized body before issuing a
grant.

The generic proxy does not copy arbitrary client headers. In legacy mode an
inbound grant header is dropped; in protected mode the backend overwrites it
with its own signed value.

The worker independently verifies canonical base64url, exact JSON fields,
signature, nonce size, device/action/request/method/path/query/body bindings and
the time window. Read grants are process-single-use. Write grants are consumed
transactionally in a separate SQLite ledger using SHA-256 of nonce, device and
request id; they remain single-use after worker restart without storing the raw
claims.

Missing, malformed, duplicated/unknown-field, wrong-secret, wrong-action,
wrong-request, wrong-method, wrong-path, changed-query, changed-body, future,
expired, overlong or replayed grants fail with HTTP 403. A durable-ledger error
also fails closed before a protected write reaches the writer.

`MemoryReadAccess` and `MemoryWriteAccess` remain storage permissions, not caller
authentication.

## Worker-mode attestation

Every worker response under `/experimental/agent3/memory` is marked internally
with:

```text
X-Kaliv-Agent3-Memory-Store: protected
```

The authenticated backend refuses to expose the upstream body unless this exact
attestation is present. This prevents a backend configured for `protected` from
silently serving a mismatched worker's legacy memory route. The header is an
internal loopback assertion and is not accepted from the client.

## Remote disclosure policy

Every response is metadata-only:

- `value` is `[redacted]` (or empty for a deleted tombstone);
- `source_ref` is always `null`;
- secret rows are excluded from list/search and returned as not found even when
  their id is known;
- search covers subject/predicate metadata only and never decrypts or scans a
  value, envelope or ciphertext;
- there is no remote context-preview or secret reveal route.

## Bounded local planner context

Protected planner memory is a separate server-owned provider, not a remote
memory route and not a duck-typed legacy `MemoryStore`.

The planner resolves its route target before asking the provider for any values.
The protected provider accepts only `local`; a cloud target or a private-cloud
consent flag is rejected before the first decrypt operation and before the
planner model is called.

For an accepted local request:

- only active, confirmed, unexpired, non-secret rows are eligible;
- public, operational and private values may be used locally;
- source provenance is never rendered;
- output is capped at 12,000 characters and 50 records;
- candidate decryption is independently capped at 24,000 characters and 100
  records, normally at no more than twice the requested output limits;
- subject filters are canonical, unique and capped at 20;
- values are rendered by the existing untrusted JSON memory envelope with
  markup characters escaped;
- the plan store persists only included/excluded ids, character count, target
  and SHA-256 receipt — never the decrypted context text.

A zero budget returns an empty receipt without decrypting. Protected and legacy
planner sources cannot be configured simultaneously. In protected mode the
legacy context-preview route and plaintext planner store remain absent.

## Write policy

The boundary accepts only `private` create/correct/delete operations. Secret
writes remain local-management-only. Public/operational values belong to the
plaintext class and are not created through the protected writer.

Creates encrypt value and server-owned request provenance before commit.
Corrections and deletes require exact `expected_updated_at` compare-and-swap;
stale operations fail without a partial replacement. Responses never echo the
submitted plaintext.

## Deliberate remaining boundaries

- protected mode is still behind the global dormant `KALIV_AGENT3_ENABLED=1`;
- draft PR #206 remains the independent canary leak-surface promotion gate;
- no secret reveal, bulk decrypt, value search, embedding or plaintext logging;
- no protected memory is sent to cloud, including with a consent flag;
- no implicit migration, key rotation or recovery bypass;
- no physical Windows backup/restore claim yet.
