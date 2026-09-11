# Memory 4.0 W03 — completed-turn persistence orchestration

Status: W03-A is a default-off internal composition boundary. It does not activate normal-chat persistence, Agent 3, cloud writes or production behavior.

## Purpose

W01 owns candidate extraction authority. W02 owns deterministic consolidation planning and durable write execution. W03-A composes those landed boundaries for one completed turn without becoming a new model, storage or HTTP authority.

The shared `app.memory` orchestrator is storage-neutral. Callers inject:

1. an async W01 extraction callback;
2. a synchronous W02-A plan-preparation callback that owns the trusted current durable snapshot;
3. a synchronous W02-B application callback that owns the actual store transaction.

W03-A itself opens no database, imports no Agent 3 storage implementation, mounts no route and performs no model/network call.

## Pre-extraction turn boundary

Before an injected extractor can observe a turn, W03-A applies the exact W01 completed-turn validation/canonicalization contract:

- `user_text` and `assistant_text` are non-empty and bounded by the W01 hard limit;
- `source_ref` is non-empty and bounded;
- canonical surrounding whitespace is removed exactly as W01 does;
- invalid/oversized turns fail before the extraction callback is invoked.

This prevents a custom composition callback from bypassing W01's pre-model data bound.

## Candidate rebinding

Custom extraction does not gain provenance or review authority merely by returning a `MemoryCandidate` object.

W03-A revalidates the candidate batch against W02's bounded candidate contract, then requires:

- every candidate `source_ref` to equal the validated completed-turn `source_ref`;
- every `user_explicit` candidate to carry non-empty evidence literally present in the validated user turn;
- the candidate value to be literally contained in that user evidence;
- every `confirmed` candidate to match the one server-owned W01 auto-confirm shape for the current turn.

A confirmed auto-persistable candidate must therefore be exactly:

- `subject=user`;
- `predicate=verbatim_user_statement`;
- `kind=note`;
- `sensitivity=private`;
- `source_type=user_explicit`;
- caller-owned `source_ref` equal to the current turn;
- `confidence=1.0`;
- `review_status=confirmed`;
- `value == evidence == validated user_text`.

W03-A also reruns the W01 credential heuristic. Because a custom extractor no longer carries the model-proposed labels that W01 inspected before normalization, W03-A conservatively scans the bounded turn text itself as label-bearing input too. Credential-like turns cannot be auto-persisted as private confirmed memory.

Pending, secret, inferred, imported, tool-observation and structured semantic proposals are deferred before plan or storage callbacks. W03-A does not silently upgrade them.

## W02 plan binding

The injected W02-A callback may read the current trusted durable snapshot and build the normal `ConsolidationPlan`, including the already-landed exact pending-to-confirmed verbatim promotion.

Before W03-A allows that plan to reach a write callback it proves that:

- the plan contains exactly the eligible candidate multiset and no injected candidate;
- the plan receipt is still pre-store (`sent_to_store=false`);
- considered/create/dedupe/supersede/skip counts exactly match the plan actions;
- touched durable ids exactly match action `existing_id` values.

W02-B still performs its own fresh-state replan under the write transaction. W03-A does not replace that race/authority check.

## Write receipt binding

After the injected W02-B callback returns, W03-A accepts only the versioned safe write-receipt projection. It rechecks:

- exact schema and field set;
- considered/action accounting;
- bounded, unique durable ids;
- superseding ids are created ids;
- created/deduped/superseded roles do not reuse ids incompatibly;
- replay receipts claim no fresh mutation;
- `sent_to_store=true`.

The W03 receipt exposes counts and durable ids only. It does not expose memory values, extraction evidence or source provenance.

## Non-goals

W03-A adds no:

- `/api/v1/chat` persistence hook;
- public/internal HTTP memory-write endpoint;
- startup/background scheduler;
- automatic Ollama call;
- database selection or DPAPI/provider selection;
- Agent 3 activation dependency;
- cloud/private-cloud write grant;
- semantic stale-fact replacement;
- delete authority;
- production activation.

A later W03 integration slice must choose and qualify a concrete product composition explicitly. Landing W03-A alone does not imply that any normal user turn is persisted automatically.

`production_activation=false`
