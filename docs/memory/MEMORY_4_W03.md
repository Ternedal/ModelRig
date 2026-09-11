# Memory 4.0 W03-A — completed-turn persistence orchestration

Status: internal implementation candidate; no chat hook, HTTP write route or production activation.

W03-A composes the landed W01 extraction and W02 planning/write boundaries for one completed turn without moving storage authority into the shared `app.memory` package.

## Boundary

`MemoryTurnPersistenceOrchestrator` receives three injected callbacks:

1. async W01 candidate extraction for one validated `CompletedMemoryTurn`;
2. W02 plan preparation for an eligible candidate tuple;
3. W02 durable apply for the returned `ConsolidationPlan`.

The shared orchestrator opens no database and imports no Agent 3 storage classes. It does not import or select the local Ollama adapter; a caller must explicitly inject an extractor that uses it.

## Automatic persistence authority

W03-A deliberately auto-forwards only the already-hardened server-owned W01 representation of a complete explicit user statement:

- `subject=user`;
- `predicate=verbatim_user_statement`;
- `kind=note`;
- `sensitivity=private`;
- `source_type=user_explicit`;
- `confidence=1.0`;
- `review_status=confirmed`;
- `value == evidence == completed user_text`;
- `source_ref == completed turn source_ref`.

Everything else is deferred **before** W02 callbacks are invoked. That includes semantic/model-authored structure, pending candidates, inferred/imported/tool-observed candidates and secret candidates.

This makes W03-A narrower than the generic W02 writer. W02 remains capable of storing reviewed/pending candidates when an explicit trusted caller chooses to do so; W03-A does not grant that authority to automatic completed-turn orchestration.

## Fail-closed composition

Before storage can run, W03-A independently proves:

- the completed turn passes the existing W01 turn validator;
- extraction is actually asynchronous and returns the W01 tuple form;
- the extracted batch still satisfies W02 hard bounds/authority validation;
- every candidate provenance reference binds to the exact completed turn;
- the injected W02 plan is a real `ConsolidationPlan`, contains exactly the eligible candidate batch and has an internally consistent pre-store receipt;
- the W02 write receipt uses the expected schema, binds the exact eligible count, balances created/deduped/skipped outcomes, balances supersede ids, contains only bounded ids/counts and reports `sent_to_store=true`.

Extraction, planning and durable-apply failures are surfaced as bounded W03-A failures with the original exception retained only as the cause.

## Receipt

`kaliv-memory-turn-persistence/v1` contains only:

- extracted candidate count;
- automatically eligible count;
- deferred count;
- normalized W02 write receipt counts/ids/replay status, or `null` when nothing was eligible.

It never contains user/assistant turn text, candidate values, evidence, source references, raw model output or protected payloads.

## Deliberately absent

W03-A adds no:

- `/api/v1/chat` persistence hook;
- HTTP write route;
- scheduler/background write;
- Agent 3 activation dependency;
- cloud extraction or cloud write grant;
- correction/delete authority;
- model-selected storage operation;
- production activation.

A later separately reviewed integration slice is still required before normal chat can automatically persist completed-turn memory.

`production_activation=false`.
