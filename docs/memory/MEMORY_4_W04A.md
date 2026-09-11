# Memory 4.0 W04-A — default-off loopback completed-turn write surface

Status: landed, independently default-off, with the W04-H1 admission/privacy
hardening. The surface is local-only and does not itself activate normal-chat
persistence.

`production_activation=false`

## Purpose

W03 landed the in-process write composition from a bounded completed turn through
W01 extraction and fresh transactional W02 planning to durable storage. W03 did
not expose that composition over HTTP.

R05 normal-chat retrieval already talks to an independent loopback-only Memory 4
worker surface. W04-A adds the corresponding **write-side worker boundary**. The
separately landed W04-B normal-chat hook may call this surface only after a valid
completed streamed turn; W04-A remains independently gated and testable.

W04-A is therefore an integration primitive, not production activation.

## Flags

The write surface owns two independent flags:

- `KALIV_MEMORY4_WRITE_ENABLED=1` — mounts the W04-A loopback route. Default off.
- `KALIV_MEMORY4_WRITE_INDEXED_PROTECTED=1` — when protected storage is selected,
  use the already-migrated #1218 keyed blind index for canonical verbatim exact
  matching. Default off.

Neither flag is implied by:

- `KALIV_MEMORY4_CONTEXT_ENABLED`;
- `KALIV_MEMORY4_CHAT_ENABLED`;
- `KALIV_MEMORY4_CHAT_WRITE_ENABLED`;
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

### W04-H1 admission-before-read boundary

The request body is deliberately **not** declared as a FastAPI/Pydantic endpoint
parameter. The handler first evaluates the loopback policy and only an admitted
request may proceed to body I/O. A denied caller therefore cannot cause private
turn bytes to be read or parsed before the `403` decision.

After loopback admission, W04-A enforces the server-owned raw-body limit
`MAX_COMPLETED_TURN_WRITE_BODY_BYTES` (512 KiB) before JSON/Pydantic parsing. A
valid completed turn is much smaller in its canonical UTF-8 form; the extra space
allows ordinary JSON escaping without turning the parser into an unbounded input
surface. Declared `Content-Length` is checked first when present, and the same
limit is enforced incrementally while streaming when it is absent.

Only after the raw byte gate passes does W04-A parse the exact
`CompletedTurnWriteBody` schema. Empty, malformed, oversized, wrong-type,
missing-field and unknown-field bodies all fail with the same fixed response:

- status: `422`;
- detail: `invalid memory completed-turn write request`.

Pydantic/JSON exception text and rejected `user_text`, `assistant_text` or
`source_ref` are never reflected into that response. This is intentionally
stricter than FastAPI's default validation response, which may include rejected
input.

The validated body is converted to `CompletedMemoryTurn` and handed to the landed
`MemoryCompletedTurnWriteService`. W03 then re-applies W01 turn bounds before the
extractor sees the turn and revalidates extracted candidates through W02 before a
storage adapter may commit them.

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

Loopback admission failure returns `403` before request-body consumption, JSON
parsing, W01 extraction or W03 execution.

All body-size/decode/schema validation failures return the fixed redacted `422`
detail documented above. Caller input and framework validation internals are not
included.

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
- W04-H1 denial before any ASGI body receive;
- strict body fields/types with one redacted fixed `422` response;
- malformed private input non-reflection;
- declared and streamed raw-body byte bounds before extraction/parsing;
- empty extraction/no-store response;
- sanitized extraction/write failures;
- legacy create and exact dedupe;
- response value/source-ref non-leakage;
- protected write with empty plaintext columns;
- explicit indexed migration followed by keyed-selector write;
- invalid legacy/indexed mode rollback;
- idempotent cleanup;
- runtime lifespan nesting and scheduler authority-marker preservation.

Existing full-repository scheduler tests additionally verify that the documented
production entrypoint still exposes the scheduler as the root lifespan authority.

## Deliberate non-goals

W04-A adds no:

- production activation;
- response-stream interception or buffering (that remains W04-B's backend role);
- background queue, retry daemon or scheduler;
- cloud extractor/write path;
- private-cloud memory grant;
- Agent 3 activation dependency;
- automatic #1218 sidecar migration/repair;
- semantic stale-fact replacement or trusted review UI;
- new correction/delete authority.

W04-B is a separately reviewed and independently default-off caller of this
surface. W04-H1 changes only the worker HTTP admission/validation boundary; it
does not change W04-B's path, request fields, receipt contract or activation.
