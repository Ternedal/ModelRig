# Agent 3 protected memory API boundary

**Status:** DORMANT — implemented and testable, not mounted by production startup.

This slice defines the first HTTP boundary that can operate on a completed
T-033 protected memory store without turning the storage access enums into
authentication.

## Authorization contract

`build_protected_memory_router` has no permissive default. Its caller must inject
an authorizer that returns a typed `ProtectedMemoryApiGrant` bound to:

- a canonical authenticated principal;
- the exact typed action (`status`, `read_metadata`, or `write_private`);
- the exact `X-Request-ID`;
- an issue and expiry time with a maximum 120-second lifetime.

Missing, malformed, future-dated, expired, overlong, wrong-action,
wrong-request, wrong-type, or failed authorization is HTTP 403. A boolean is
not a grant.

The intended later production authorizer is the authenticated Go gateway. This
slice does **not** invent or accept a second user password and does not claim
that `MemoryReadAccess` or `MemoryWriteAccess` authenticates a caller.

## Remote disclosure policy

Every response is metadata-only:

- `value` is `[redacted]` (or empty for a deleted tombstone);
- `source_ref` is always `null`;
- secret rows are excluded from list/search and are returned as not found even
  when their id is known;
- search covers subject/predicate metadata only and never decrypts or scans a
  value, envelope, or ciphertext;
- there is no remote context-preview or secret reveal route.

## Write policy

The boundary accepts only `private` create/correct/delete operations. Secret
writes remain local-management-only. Public/operational values belong to the
plaintext class and are not created through this protected writer.

Creates encrypt value and server-owned request provenance before commit.
Corrections and deletes require exact `expected_updated_at` compare-and-swap;
stale operations fail without a partial replacement. Responses never echo the
submitted plaintext.

## Deliberate non-goals

- no import from `production_mount.py`;
- no environment switch or implicit store replacement;
- no backend proxy/signing implementation yet;
- no planner-store selection;
- no secret reveal, bulk decrypt, value search, embedding, logging, or preview;
- no physical Windows backup/restore claim.

The next slice may wire an exact protected-store mode only after the Go gateway
can produce and the worker can validate the request grant without fallback to
the legacy plaintext runtime.
