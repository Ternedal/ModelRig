# Memory 4.0 R04-H1 — context request boundary hardening

**Tracker:** #1262  
**Parent architecture:** #1167  
**Activation:** `production_activation=false`

R04 is the private loopback worker surface used by the guarded normal-chat R05
integration to build memory context before a model call:

`POST /experimental/memory4/context-for-turn`

The route already required a loopback caller, but its FastAPI handler previously
declared `ContextForTurnBody` as an endpoint parameter. FastAPI/Pydantic therefore
read and validated the JSON body before the handler could run the loopback policy.
That ordering was weaker than the landed W04-H1 completed-turn write boundary.

R04-H1 makes the admission and validation boundary explicit without changing
retrieval, storage or receipt semantics.

## Request ordering

The handler now accepts only the raw `Request` at dispatch time.

1. evaluate the existing loopback policy;
2. only for an admitted caller, read the request stream;
3. cap body bytes at 256 KiB before JSON/Pydantic parsing;
4. validate the existing strict `ContextForTurnBody`;
5. construct the existing `ContextForTurnRequest`;
6. call the unchanged `MemoryContextForTurnService`.

A denied caller therefore cannot make the route read the query body. The body cap
is enforced both against a declared `Content-Length` and while consuming ASGI
chunks, so a missing or dishonest length header cannot bypass it.

The accepted logical request contract is unchanged:

- `query`: strict non-empty text, max 4,096 characters;
- `target`: `local` or `cloud`, default `local`;
- `subjects`: at most 64 strict strings; canonical/bounded subject validation
  remains owned by the service;
- `max_results`: strict integer 1..50, default 12;
- `max_context_chars`: strict integer 1..12,000, default 12,000;
- unknown fields remain forbidden.

## Redacted validation failures

Malformed JSON, empty or oversized bodies, invalid field types/bounds and unknown
fields now return one fixed response:

`422 {"detail":"invalid memory context request"}`

R04 does not return Pydantic's validation structure because it may contain the
rejected `input`, including the current user's private memory query, subject
filters or unexpected caller fields.

The existing service-level request errors remain `400`; storage/retrieval/service
failures retain the existing bounded `503` behavior. Successful responses retain
the exact R04 service schema, context and receipt/hash contract.

## Regression boundary

The focused regression suite proves that:

- a non-loopback request receives `403` without the ASGI receive channel being
  touched;
- strict-body failures never reflect private marker values;
- malformed JSON uses the same fixed redacted `422`;
- body bytes are bounded even without `Content-Length`.

The suite lives under `tests/support` and is invoked by the existing Memory 4
top-level qualification gate, so no new top-level test inventory authority is
introduced.

R04-H1 grants no new memory class, private-cloud authority, storage write,
scheduler, Agent 3, model, tool, release or production activation authority.

`production_activation=false`
