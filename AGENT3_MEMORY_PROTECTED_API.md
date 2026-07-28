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
- `protected`: the protected reader/writer/API are selected, while the legacy
  store, legacy context-preview and plaintext planner-memory integration are not
  mounted.

Protected startup requires all of the following before its route is included:

- a completed, internally consistent migration receipt for the selected DB;
- a provider/key-scope matching every protected envelope (Windows production:
  DPAPI current-user);
- `KALIV_AGENT3_MEMORY_API_SECRET` containing at least 32 bytes.

Unknown modes, missing/short secrets, incomplete migrations, wrong providers or
wrong key scopes abort the mount. There is no automatic migration and no
protected-to-legacy fallback.

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
- issue and expiry timestamps.

The generic proxy does not copy arbitrary client headers. In legacy mode an
inbound grant header is dropped; in protected mode the backend overwrites it
with its own signed value.

The worker independently verifies canonical base64url, exact JSON fields,
signature, nonce size, device/action/request/method/path bindings and the time
window. A valid nonce is consumed once in a bounded in-memory replay cache.
Missing, malformed, duplicated/unknown-field, wrong-secret, wrong-action,
wrong-request, wrong-method, wrong-path, future, expired, overlong or replayed
grants fail with HTTP 403.

`MemoryReadAccess` and `MemoryWriteAccess` remain storage permissions, not caller
authentication.

## Remote disclosure policy

Every response is metadata-only:

- `value` is `[redacted]` (or empty for a deleted tombstone);
- `source_ref` is always `null`;
- secret rows are excluded from list/search and returned as not found even when
  their id is known;
- search covers subject/predicate metadata only and never decrypts or scans a
  value, envelope or ciphertext;
- there is no remote context-preview or secret reveal route.

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
- protected planner memory remains disabled until a separate bounded local-only
  compiler can be proven without bulk decrypt or prompt leakage;
- no secret reveal, bulk decrypt, value search, embedding or plaintext logging;
- no implicit migration, key rotation or recovery bypass;
- no physical Windows backup/restore claim yet.
