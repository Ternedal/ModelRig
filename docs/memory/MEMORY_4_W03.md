# Memory 4.0 W03 — bounded completed-turn durable write orchestration

Status: implementation candidate, default-off and not wired to normal chat.

`production_activation=false`

## Purpose

W01 and W02 deliberately landed as separate authority boundaries:

- W01 accepts one bounded completed turn, optionally calls a local extractor, and
  emits validated `MemoryCandidate` objects. Raw model JSON cannot cross W01.
- W02-A accepts only validated candidates plus a trusted bounded durable snapshot
  and produces deterministic `create`, `dedupe`, `supersede` or `skip` actions.
- W02-B reruns W02-A against fresh durable state under the existing write
  transaction before any mutation.

Before W03, no neutral component connected those boundaries for one completed
turn. W03 adds that composition without adding a chat hook, HTTP route, scheduler
or production activation.

## Neutral orchestration boundary

`worker/app/memory/write_service.py` defines the storage-neutral W03 core:

- `MemoryCompletedTurnWriteService`
- `CompletedTurnWriteReceipt`
- `DurableCandidateWrite`
- `MemoryTurnWriteError`
- receipt schema `kaliv-memory-completed-turn-write-receipt/v1`

The service receives exactly two injected capabilities:

1. an async completed-turn extractor returning a tuple of validated
   `MemoryCandidate` objects;
2. a candidate-batch committer returning only a value-free durable write result.

The neutral service imports no SQLite store, DPAPI/provider, HTTP client, FastAPI
router, Go chat integration or Agent 3 production mount.

The candidate batch is revalidated through `MemoryConsolidator` before the
committer can see it. This validation-only plan grants no storage authority and is
discarded; storage adapters make the authoritative plan from a fresh bounded
snapshot under their existing write transaction.

## Empty and failure behavior

An empty W01 candidate tuple is a deterministic no-store result:

- `candidate_count=0`
- all mutation/dedupe counts are zero
- all id lists are empty
- `sent_to_store=false`

The committer is not invoked.

Extraction failure, a non-tuple candidate batch, W02 validation failure, storage
failure or malformed durable receipt fails closed with `MemoryTurnWriteError`.
No fallback path writes raw extractor output directly.

## Durable receipt boundary

The public W03 receipt may expose only:

- schema;
- candidate/considered counts;
- created, superseded, superseding and deduped durable ids;
- skipped count;
- replay status;
- whether a non-empty batch crossed the store boundary.

It has no fields for candidate value, evidence, `source_ref`, extractor/model
output, protected envelopes, encryption metadata or blind-index fingerprints.

The neutral service revalidates durable receipt shape and accounting. For a
non-empty batch, `created + deduped + skipped` must equal the candidate count;
a supersede action's replacement is already counted as created. Superseding ids
must correspond to created ids, replay receipts cannot report mutations, and id
sets cannot contain duplicates or contradictory overlaps.

## Storage compositions

`worker/app/agent3/memory_turn_commit.py` provides explicit storage adapters.
They are outside the neutral package because they depend on the existing Memory 3
storage substrate.

### Legacy

`commit_legacy_candidates(...)`:

1. validates the W01 batch with W02-A;
2. enters the existing `MemoryStore` write transaction;
3. reads only the bounded relevant W02 snapshot;
4. reruns W02-A against that fresh snapshot;
5. applies the fresh W02-B actions before the transaction releases;
6. projects the W02-B receipt into `DurableCandidateWrite`.

There is no caller-supplied write operation or durable id authority.

### Protected

`commit_protected_candidates(...)` requires exact
`MemoryWriteAccess.LOCAL_MANAGEMENT`, the completed protected-memory migration and
the existing `ProtectedMemoryWriter` transaction. Values and source references
continue through the existing protection codec and never gain a W03 plaintext
storage path.

The non-indexed protected composition intentionally retains W02-B's existing hard
bound for canonical verbatim history.

### Indexed protected

`commit_indexed_protected_candidates(...)` composes W03 with the protected
blind-index slice landed through #1218.

It does **not** create, migrate or repair the blind index. The sidecar must have
been explicitly migrated already. Runtime completeness is checked before and
after mutation, exact matches are selected only through the keyed sidecar and are
still decrypted and revalidated before W02-A acts. Missing or stale sidecar state
fails closed.

## Authority preservation

W03 does not weaken W01/W02 authority:

- automatic confirmed memory remains only the server-owned complete verbatim user
  statement defined by W01 hardening;
- model-authored structured interpretations remain pending;
- pending structured state cannot supersede confirmed state;
- secret candidates remain pending at W01 and are skipped/no-auto-persist at W02;
- semantic similarity cannot create merge/supersede authority;
- no model/caller can supply a write operation, correction token, delete request,
  review authority, supersedes id or blind-index selector;
- all durable decisions are freshly replanned from bounded current state under the
  existing transaction.

## Qualification

Focused qualification is kept under `tests/support/` and invoked through the
existing T-033 top-level test entry so repository test inventory does not grow for
this slice.

Coverage includes:

- empty extraction/no-store behavior;
- raw extractor JSON passing W01 before storage;
- confirmed verbatim normalization and durable create;
- current-state exact dedupe;
- structured partial evidence staying pending and out of context;
- secret no-auto-persist behavior;
- extraction and candidate-container failure before commit;
- durable receipt mismatch rejection;
- storage failure propagation;
- value/evidence/source-ref absence from W03 receipts;
- protected storage round-trip with empty plaintext base columns;
- explicitly migrated indexed protected create and exact dedupe;
- keyed blind-index selector rather than plain SHA-256(value).

## Deliberate non-goals

W03 adds no:

- `/api/v1/chat` automatic persistence hook;
- HTTP endpoint of any kind;
- background/scheduled extraction or consolidation;
- cloud extractor or cloud write route;
- private-cloud memory grant;
- Agent 3 activation dependency;
- user-facing review UI;
- semantic stale-fact replacement authority;
- production activation.

A later separately reviewed integration slice is required before any completed
normal-chat turn can automatically invoke W03.
