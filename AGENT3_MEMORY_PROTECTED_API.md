# Agent 3 protected memory API boundary

**Status:** CONDITIONALLY SELECTABLE — the default remains `legacy`. The
`protected` surface exists only behind the global Agent 3 feature flag and an
exact store selector; configuration or verification failure aborts the mount.
This is not a release or production-readiness claim.

The boundary operates on a completed T-033 protected-memory store without
turning storage access enums into authentication. The authenticated Go gateway
mints short-lived request grants, while the loopback worker independently
verifies them before exposing the metadata-only API delivered by #296.

## Exact store selection

`KALIV_AGENT3_MEMORY_STORE` accepts exactly:

- empty or `legacy`: the historical plaintext `MemoryStore`, legacy CRUD/context
  routes and legacy planner-memory source remain unchanged;
- `protected`: the completed protected store, protected reader/writer and
  metadata-only API are selected. The legacy store and legacy context-preview
  are absent, and protected planner memory remains disabled.

Protected startup also requires:

- `KALIV_AGENT3_ENABLED=1` through the existing Agent 3 core gate;
- a completed and internally consistent migration for the selected memory DB;
- a protection provider and key scope matching every protected envelope
  (Windows production provider: DPAPI current-user);
- `KALIV_AGENT3_MEMORY_API_SECRET` containing 32–4096 bytes;
- a canonical, non-symlinked and separate
  `KALIV_AGENT3_MEMORY_GRANT_DB` path for the replay ledger.

Unknown or non-canonical modes, missing signing material, incomplete migration,
provider/key mismatch, invalid ledger path or a ledger path equal to the memory
DB fail closed. The selector imports no migrator, performs no migration and
never catches a protected failure to instantiate the legacy store.

## Authenticated gateway grant

The Bearer-authenticated Go gateway derives the paired device from the existing
authentication middleware and issues a 30-second domain-separated HMAC-SHA256
grant only for a loopback worker. The grant binds:

- schema `kaliv-agent3-memory-grant/v1`;
- a random canonical 256-bit nonce;
- authenticated device id;
- exact typed action (`status`, `read_metadata`, or `write_private`);
- canonical `X-Request-ID`;
- exact HTTP method and worker path;
- exact raw query string;
- SHA-256 of the bounded request body;
- issue and expiry timestamps.

The gateway reads at most 64 KiB plus one byte, hashes the exact body and restores
it before forwarding. It never copies arbitrary client headers upstream. In
legacy mode an inbound grant is ignored by the narrow proxy allow-list; in
protected mode the backend overwrites it with its own signed value.

## Independent worker verification

The worker validates canonical base64url, exact JSON shape, signature, nonce
size, device/action/request/method/path/query/body bindings and the validity
window. Missing, malformed, duplicated/unknown-field, wrong-signature,
wrong-action, wrong-request, changed-query, changed-body, future, stale, expired,
overlong or replayed grants return a fixed HTTP 403 response.

Read nonces are process-single-use for their bounded lifetime. Write nonces are
consumed transactionally in a separate SQLite ledger. The ledger stores only
SHA-256 digests of nonce, device and request id and survives authorizer/worker
restart. A durable-ledger error fails closed before the protected writer is
called.

`MemoryReadAccess` and `MemoryWriteAccess` remain storage permissions, not caller
authentication.

## Transport and response attestation

The worker boundary independently caps protected request bodies at 64 KiB and
binds their SHA-256 into request state before authorization. It keeps #296's
internal validation, fixed public error bodies and no-input-echo behavior.

Every worker response under `/experimental/agent3/memory` carries the internal
loopback-only attestation:

```text
X-Kaliv-Agent3-Memory-Store: protected
```

The backend refuses to expose an upstream response body unless that exact
attestation is present. A backend configured for `protected` therefore cannot
silently serve a mismatched worker's legacy memory route. Client-supplied
attestation or grant headers are never trusted.

## Remote disclosure and write policy

Every successful response remains metadata-only:

- `value` is `[redacted]`, or empty for a deleted tombstone;
- `source_ref` is always `null`;
- local-management-only rows are absent from list/search and return not found
  even when their id is known;
- search covers subject/predicate metadata only and never decrypts or scans a
  value, envelope or ciphertext;
- authorization, validation, not-found and conflict errors are fixed and
  bounded;
- no remote context-preview or protected-value reveal route exists.

Remote create/correct/delete accepts only `private` records. Creates encrypt the
value and server-owned device/request provenance before commit. Corrections and
deletes require exact `expected_updated_at` compare-and-swap. Stale operations
leave no partial replacement, and responses never echo submitted plaintext.

## Promoted leak gate

The #291 leak gate remains active. It now permits protected reader/writer/API
symbols only inside `worker/app/agent3/memory_surface.py` and only while that
file declares the exact mount contract, no automatic migration, no fallback,
separate replay state and disabled protected planner memory. A missing marker,
a migrator import or protected symbol in another runtime boundary fails closed.

API responses and SQLite/WAL/SHM/journal surfaces continue to be scanned with
synthetic markers. The dedicated Windows workflow remains `contents: read` and
runs the Go grant tests, gateway verifier, store selection, API boundary,
reader/writer and leak gates, including real current-user DPAPI coverage.

## Deliberate remaining boundaries

- `legacy` remains the default and protected selection remains behind
  `KALIV_AGENT3_ENABLED=1`;
- protected planner/context is disabled; no private protected memory is sent to
  local or cloud model prompts by this slice;
- no secret reveal, bulk decrypt, value search, embeddings, outcome injection or
  plaintext logging;
- no automatic migration, key rotation, backup/restore operation or recovery
  bypass;
- no normal-chat routing change;
- no release, physical-rig proof or production-readiness claim.

A later slice must separately prove any bounded protected planner context. It
must not broaden this gateway/API boundary or introduce a protected-to-legacy
fallback.
