# Agent 3 protected memory API boundary

**Status:** DORMANT — implemented and testable, not mounted by production startup.

This slice defines a request-bound HTTP boundary over a completed T-033
protected-memory store. It does not turn storage access enums into authentication
and it does not activate a route.

## Authorization contract

`build_protected_memory_router` has no permissive default. Its caller must inject
an authorizer that returns a typed `ProtectedMemoryApiGrant` bound to:

- a canonical authenticated principal;
- the exact typed action (`status`, `read_metadata`, or `write_private`);
- the exact canonical `X-Request-ID`;
- an issue and expiry time with a maximum 120-second lifetime.

Missing, malformed, future-dated, expired, inverted, overlong, wrong-action,
wrong-request, wrong-type, boolean-timestamp, or failed authorization is HTTP
403 with a fixed public error body. Authorization is evaluated before a private
request body is read.

The intended later authorizer is the authenticated gateway boundary. This slice
does **not** invent a second user password and does not claim that
`MemoryReadAccess` or `MemoryWriteAccess` authenticates a caller.

## Bounded request parsing

Create and correction bodies are read only after authorization, capped at 64
KiB, decoded and validated inside the route. Validation errors are converted to
a fixed 422 response rather than FastAPI/Pydantic's default input-bearing error
shape. Invalid and oversized payloads therefore cannot be echoed into API
responses or committed to storage.

## Remote disclosure policy

Every successful response is metadata-only:

- `value` is `[redacted]` (or empty for a deleted tombstone);
- `source_ref` is always `null`;
- local-management-only rows are excluded from list/search and returned as not
  found even when their id is known;
- search covers subject/predicate metadata only and never decrypts or scans a
  value, envelope, or ciphertext;
- public authorization, validation, not-found and conflict errors use fixed
  bounded messages;
- there is no remote context-preview or protected-value reveal route.

The contract test feeds synthetic markers through valid, invalid, oversized,
unauthorized, stale and local-management-only requests. It uses the landed
T-033 leak gate to prove every collected HTTP response is marker-free and scans
the SQLite/WAL/SHM/journal family for both values and protected provenance.

## Write policy

The boundary accepts only `private` create/correct/delete operations. Values
classified for local management remain local-management-only. Public and
operational values belong to the plaintext class and are not created through
this protected writer.

Creates encrypt value and server-owned principal/request provenance before
commit. Corrections and deletes require exact `expected_updated_at`
compare-and-swap; stale operations fail without a partial replacement.
Responses never echo submitted plaintext.

## Deliberate non-goals

- no import from `production_mount.py`;
- no route, startup or environment-switch change;
- no backend proxy or grant-signing implementation;
- no planner or outcome wiring;
- no protected value reveal, bulk decrypt, value search, embedding, logging or
  preview;
- no automatic migration, backup/restore operation, key rotation, release or
  production activation.

The router remains a loose `APIRouter` until a separate, explicitly approved
runtime-selection slice exists.
