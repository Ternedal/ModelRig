# Memory 4.0 W03-A — strict completed-turn auto-persistence gate

Status: default-off internal safety slice for #1222. It supplements the landed
W03 completed-turn write service; it does not replace that service and does not
activate normal-chat persistence.

`production_activation=false`

## Why W03-A exists alongside W03

The general W03 write service composes validated W01 candidates with the existing
W02 durable-write boundary. That service deliberately preserves W02 semantics,
including bounded pending candidates.

W03-A is narrower. It is the safety gate intended for a future separately reviewed
automatic persistence integration. It allows only the one candidate shape for
which W01 itself owns confirmation authority: the canonical verbatim user
statement. Model-authored semantics, pending candidates and secret data do not
cross its planning/storage callbacks.

## Flow

`CompletedTurnMemoryOrchestrator.persist(...)`:

1. validates/canonicalizes one `CompletedMemoryTurn` through the existing W01
   completed-turn boundary;
2. invokes an explicitly injected asynchronous W01 extraction callback;
3. revalidates the returned bounded candidate tuple and binds provenance to the
   completed turn;
4. partitions candidates into auto-persistable and deferred sets;
5. returns a deterministic no-write receipt when nothing is eligible, without
   calling either W02 callback;
6. sends only the eligible tuple to an injected W02 plan-preparation callback;
7. requires the returned `ConsolidationPlan` and its pre-store receipt to cover
   exactly that tuple;
8. sends that exact plan to an injected W02 apply callback;
9. validates/projects the durable W02 result into a value-free W03-A receipt.

The shared module opens no database and imports neither Agent 3 storage nor the
local Ollama extraction adapter.

## Only canonical confirmed verbatim statements cross automatically

A candidate is eligible only when all of the following are true:

- `subject == "user"`
- `predicate == "verbatim_user_statement"`
- `kind == "note"`
- `sensitivity == "private"`
- `source_type == "user_explicit"`
- `confidence == 1.0`
- `review_status == "confirmed"`
- `value == evidence`
- `value`/`evidence` equals the canonical completed user turn
- `source_ref` equals the completed turn's source reference

Every other valid W01 candidate is deferred before W02 planning/storage. That
includes pending structured semantics, secret candidates, inferred candidates,
imports and tool observations.

## Fail-closed contracts

W03-A rejects rather than guesses when:

- the extraction callback is not asynchronous;
- extraction returns a non-tuple, over-bound batch, duplicates or malformed
  candidate authority/provenance;
- the W02 planner returns a plan not bound exactly to the eligible tuple;
- the plan receipt does not match its actions;
- the W02 apply result has an invalid schema/count/id/replay/store state or does
  not account for every planned action.

Exceptions from injected extraction/planning/storage implementations propagate.
A storage failure cannot be converted into a success-like W03-A receipt.

## Receipt

`CompletedTurnPersistenceReceipt` contains only:

- schema;
- extracted count;
- eligible count;
- deferred count;
- a sanitized durable W02 receipt containing counts, durable ids, replay state
  and store state.

Candidate value, evidence, source reference, model output and protected payloads
have no representation in the receipt.

## Deliberately not included

W03-A adds no:

- `/api/v1/chat` persistence hook;
- public/internal HTTP memory-write route;
- scheduler or background write loop;
- Agent 3 activation dependency;
- cloud/private-cloud write authority;
- semantic auto-correction or delete authority;
- production activation.

A later separately reviewed integration slice is still required before normal-chat
automatic persistence can exist.
