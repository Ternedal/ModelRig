# Memory 4.0 W04-A — default-off loopback completed-turn write surface

Status: landed implementation, with W04-H1 request-boundary privacy hardening.
The surface is local-only, independently flagged and does not by itself connect
normal chat to automatic persistence.

`production_activation=false`

## Purpose

W03 landed the in-process write composition from a bounded completed turn through
W01 extraction and fresh transactional W02 planning to durable storage. W03 did
not expose that composition over HTTP.

R05 normal-chat retrieval already talks to an independent loopback-only Memory 4
worker surface. W04-A adds the corresponding **write-side worker boundary** before
any streaming chat integration is reviewed. This keeps worker extraction/storage
failures independently testable instead of embedding them directly in the Go chat
proxy.

W04-A is therefore an integration primitive, not normal-chat activation.

## Flags

The write surface owns two independent flags:

- `KALIV_MEMORY4_WRITE_ENABLED=1` — mounts the W04-A loopback route. Default off.
- `KALIV_MEMORY4_WRITE_INDEXED_PROTECTED=1` — when protected storage is selected,
  use the already-migrated #1218 keyed blind index for canonical verbatim exact
  matching. Default off.

Neither flag is implied by:

- `KALIV_MEMORY4_CONTEXT_ENABLED`;
- `KALIV_MEMORY4_CHAT_ENABLED`;
- `KALIV_AGENT3_ENABLED`.

With the W04-A write flag off, production entrypoint calls the mount but the mount
returns before storage/provider-specific imports, opens no memory writer/provider
and publishes no write route.

The indexed-protected flag is invalid in legacy mode. In protected mode it never
creates or repairs the blind index: #1218 migration remains an explicit local
operator action and missing/stale index state fails closed.

## API contract

W04-A publishes one route only after explicit opt-in:

`POST /experimental/memory4/commit-completed-turn`

The route is loopback-only and receives exactly:

- `user_text` — strict string, non-empty, bounded by W01's completed-turn limit;
- `assistant_text` — strict string, non-empty, same bound;
- `source_ref` — strict string, non-empty, bounded by W01's source-ref limit.

Unknown fields are forbidden and Pydantic coercion of non-string values is not
accepted.

W04-H1 (#1239) hardens the request boundary so loopback admission is evaluated
**before any request-body consumption**. Only an admitted local request enters the
body reader. The route then enforces a server-owned 512 KiB byte ceiling
incrementally while reading the ASGI stream, before JSON/Pydantic decoding. The
ceiling is intentionally above the worst-case escaped representation of the
allowed W01 text fields while remaining far below the worker's broad global body
limit.

After that bounded read, the body is validated with the strict
`CompletedTurnWriteBody` model, converted to `CompletedMemoryTurn` and handed to
the landed `MemoryCompletedTurnWriteService`. W03 then re-applies W01 turn bounds
before the extractor sees the turn and revalidates extracted candidates through
W02 before a storage adapter may commit them.

The response is exactly the value-free W03 receipt. It can contain schema, counts,
durable ids, replay state and `sent_to_store`, but it has no representation for:

- candidate value;
- extraction evidence;
- `source_ref`;
- raw model output;
- protected envelopes;
- blind-index fingerprints or lookup key material.

## Extraction boundary

The production mount defaults to `extract_memory_candidates_local`, the existing
W01 local extraction adapter. That adapter is loopback-Ollama-only and has no
cloud/model fallback.

Tests may inject a bounded extractor to qualify storage and route composition
without invoking a model. This injection exists only on the Python composition
function; the HTTP request cannot choose an extractor or model.

Raw model JSON still terminates at W01. W04-A never accepts candidates, write
actions, review authority, durable ids, supersede targets or fingerprints from the
HTTP caller.

## Storage modes

The mount reuses the existing `KALIV_AGENT3_MEMORY_STORE` selector without
mounting or enabling Agent 3.

### Legacy

Legacy mode opens `MemoryStore` only after W04-A opt-in and commits through
W03 `commit_legacy_candidates(...)`.

### Protected

Protected mode opens the existing `ProtectedMemoryWriter` with the configured
local current-user provider. The writer itself requires the protected-memory
migration to be complete. W04-A commits only with exact
`MemoryWriteAccess.LOCAL_MANAGEMENT` authority.

### Indexed protected

If the independent indexed-protected flag is also enabled, W04-A uses W03's
`commit_indexed_protected_candidates(...)`. The #1218 sidecar must already exist,
be complete and be current. W04-A does not migrate or repair it.

## Failure and privacy behavior

Loopback admission failure returns `403` **before the request body is read**.
A denied caller therefore cannot make W04-A parse a completed-turn payload.

Empty, oversized, malformed-JSON, unknown-field, wrong-type and field-bound
validation failures all return the same fixed bounded `422` response:

`invalid memory completed-turn request`

The route does not expose Pydantic's validation structure because that structure
can contain the rejected `input`. The 422 body therefore contains no reflected
user text, assistant text, `source_ref` or unexpected private field value.

Extraction, W03, storage, protection or sidecar failures return a generic `503`
with the fixed public detail:

`memory completed-turn write unavailable`

Private exception strings are chained internally but are not copied into the HTTP
body.

W04-A adds no response field carrying user/assistant text or source provenance.
Protected storage continues to keep sensitive value/source-ref plaintext out of
base SQLite columns.

## Mount and lifecycle ownership

`mount_memory4_write(...)` owns route publication and process-owned write
substrate state. If construction fails after opt-in, newly added routes are
rolled back and any partially opened substrate is closed.

`close_memory4_write(...)` is idempotent and clears all W04-A app state.

Production entrypoint composes W04-A cleanup around the already composed R04
context/scheduler lifespan. Runtime enters the actual R04 wrapper, so R04 cleanup
still executes, and W04-A cleanup executes afterward. At the same time, the outer
wrapper deliberately preserves `scheduler_lifespan` as the root `__wrapped__`
authority marker used by repository lifecycle contracts; adding W04-A does not
pretend lifecycle ownership moved away from the scheduler.

## Qualification

Focused support qualification is invoked by the existing T-033 Memory 4 storage
entry point and covers:

- flag-off route/storage/provider/extractor inertness;
- loopback denial;
- strict body fields/types;
- empty extraction/no-store response;
- sanitized extraction/write failures;
- legacy create and exact dedupe;
- response value/source-ref non-leakage;
- protected write with empty plaintext columns;
- explicit indexed migration followed by keyed-selector write;
- invalid legacy/indexed mode rollback;
- idempotent cleanup;
- runtime lifespan nesting and scheduler authority-marker preservation;
- W04-H1 non-loopback denial without body consumption;
- W04-H1 fixed value-free 422 validation response;
- W04-H1 byte-ceiling enforcement before JSON/Pydantic parsing.

Existing full-repository scheduler tests additionally verify that the documented
production entrypoint still exposes the scheduler as the root lifespan authority.

## Deliberate non-goals

W04-A adds no:

- `/api/v1/chat` persistence call by itself;
- background queue, retry daemon or scheduler;
- cloud extractor/write path;
- private-cloud memory grant;
- Agent 3 activation dependency;
- automatic #1218 sidecar migration/repair;
- semantic stale-fact replacement or trusted review UI;
- production activation.

W04-B is the separately reviewed slice that may capture a successfully completed
normal-chat user/assistant turn and invoke this loopback worker surface. W04-H1
does not change W04-B activation or persistence semantics; it only hardens the
worker HTTP admission/validation boundary.
