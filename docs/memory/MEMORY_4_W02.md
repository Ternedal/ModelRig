# Memory 4.0 W02 — authority-safe consolidation and durable writes

Status: W02-A landed through PR #1206; W02-B is the default-off storage composition implemented by #1213.

This document is the write-side companion to `MEMORY_4.md`. It exists because the W01 authority hardening in #1202 materially changed what consolidation is allowed to mean.

## Why W02 is split

Memory 4.0 deliberately separates **deciding what a candidate means for storage** from **mutating storage**.

- **W02-A** (`worker/app/memory/consolidation.py`) is storage-neutral and produces a bounded deterministic `ConsolidationPlan`. It never opens a database and every receipt says `sent_to_store=false`.
- **W02-B** (`worker/app/agent3/memory_consolidation_writer.py`) is the local storage composition. It accepts only a W02-A plan, acquires the existing storage transaction, rebuilds the candidate batch from that in-process plan, takes a fresh bounded snapshot and reruns W02-A before any mutation.

This prevents an old or hand-built plan from turning a model proposal into write authority.

## W01 authority inherited by W02

After #1202, literal grounding proves only the user's exact statement. It does not prove a model-authored semantic relation such as `favorite_city=Copenhagen`.

The only automatically confirmed W01 shape is therefore the server-owned canonical verbatim note:

- `subject=user`;
- `predicate=verbatim_user_statement`;
- `kind=note`;
- `sensitivity=private`;
- `source_type=user_explicit`;
- `confidence=1.0`;
- `value == evidence`, representing the canonical complete user turn.

Structured subject/predicate interpretations remain `pending`. W02-A independently revalidates that rule; W02-B does not weaken it.

## W02-A planner boundary

W02-A accepts at most 16 candidates and 128 active durable rows, with a 64,000-character aggregate text budget. It validates every candidate/record again and canonicalizes candidate order before planning.

Storage keys are exact strings. W02 does not case-fold or otherwise normalize model-authored `subject`/`predicate` values into a shared semantic identity. `Anders/Project_Status` and `anders/project_status` therefore remain distinct unless a later trusted review boundary explicitly says otherwise. Silent case normalization would itself be semantic merge authority.

Its decisions are:

- `create` — a new pending proposal or a new confirmed verbatim statement may be stored;
- `dedupe` — an exact durable value already exists with sufficient sensitivity/review authority;
- `skip` — for example a duplicate inside the batch or a secret candidate that is outside this persistence slice;
- `supersede` — only the narrow `exact_verbatim_authority_promotion` case: the same canonical verbatim statement already exists as exactly one pending row and is now present in the hardened confirmed W01 shape.

Different verbatim statements are independent log entries. W02-A never interprets two different utterances as revisions of one semantic fact merely because they share `user/verbatim_user_statement`.

Semantic stale-fact replacement still requires a separate trusted review authority. A model-proposed key is not enough.

## W02-B writer boundary

W02-B exposes two local composition functions:

- `apply_legacy_consolidation_plan(...)` for the existing `MemoryStore`;
- `apply_protected_consolidation_plan(...)` for the existing `ProtectedMemoryWriter` with exact `MemoryWriteAccess.LOCAL_MANAGEMENT` authority.

Both functions execute inside the storage implementation's existing `BEGIN IMMEDIATE` transaction.

Before mutation W02-B:

1. verifies that the input is a bounded `ConsolidationPlan` with an internally consistent pre-store receipt;
2. reconstructs the candidate batch only from the plan's in-process `MemoryCandidate` objects;
3. reads a fresh bounded active, pending/confirmed, non-secret snapshot while the write transaction is held;
4. reruns `MemoryConsolidator`;
5. requires the fresh plan to equal the supplied plan exactly, unless the durable state proves an exact idempotent replay of a previously successful execution.

The fresh snapshot is not a whole-database scan. Structured candidates read every active non-secret pending/confirmed row in their exact `subject`/`predicate` slot, plus any trusted ids already named by the plan. Canonical verbatim candidates are narrower: because different verbatim values are independent log entries by W02-A contract, their snapshot selector also requires the exact candidate value. This keeps the 128-row safety bound meaningful without allowing 128+ unrelated historical user statements to block a new statement write.

No raw model JSON, caller-supplied operation, correction token or caller-selected supersede target enters this boundary.

## Durable mutations

`create` inserts one new active row using the candidate's exact `kind`, `sensitivity`, `source_type`, `source_ref`, confidence and `review_status`.

`dedupe` and `skip` write nothing.

`supersede` is accepted only when the fresh W02-A plan still returns reason `exact_verbatim_authority_promotion` and the target is still the same active pending private statement with the same subject, predicate and value. W02-B then:

1. inserts the confirmed candidate as a new active row with `supersedes_id=<old id>`;
2. atomically changes the old row from `active` to `superseded`;
3. commits both changes together with every other mutating action in the batch.

W02-B intentionally does **not** call the generic `correct()` methods. Those methods represent explicit user correction authority and intentionally normalize to `user_explicit + confirmed`; reusing them for W02 would silently change a pending/inferred candidate's provenance or review authority.

## Protected memory

Protected W02-B writes reuse `ProtectedMemoryWriter`'s completed-migration checks, codec, envelopes, protected metadata and transaction.

- private value/source provenance is encrypted with the existing protection codec;
- plaintext `value` remains `''` and plaintext `source_ref` remains `NULL` in protected SQLite rows;
- the writer accepts only exact `LOCAL_MANAGEMENT` authority;
- a later encryption, insert or versioning failure raises out of the outer transaction, rolling back earlier mutations from the same batch.

W02-B introduces no new protection format, key store, migration or fallback path.

## Idempotent replay

A stale plan normally fails closed. One exception exists for exact replay after a successful W02-B batch.

A former `create` may replay as a no-op only when the current active row full-matches the original candidate, including subject, predicate, value, kind, sensitivity, source type, `source_ref`, confidence, review status and absence of candidate-owned expiry. The matching row must itself be an original create, not a later version carrying a `supersedes_id`.

A former `supersede` additionally requires that the current full-match row has `supersedes_id` equal to the exact original trusted W02-A target and that the target is now `superseded`.

This rule prevents W02-A's value-level dedupe from becoming a provenance-blind replay bypass.

## Write receipt

W02-B returns `kaliv-memory-consolidation-write-receipt/v1` containing bounded counts/ids for created, superseded, superseding, deduped and skipped actions plus a `replayed` marker. It contains no memory values, evidence or source references.

## Non-goals and activation

W02-B adds no:

- HTTP route;
- `/api/v1/chat` persistence hook;
- scheduler/background consolidation;
- Agent 3 activation dependency;
- cloud write/private-cloud grant;
- model, embedding or network call;
- delete authority;
- production activation.

The writer remains an explicit local composition primitive until a later product slice defines reviewed activation and user-facing write policy.

## Qualification

W02-B is accepted only when exact-head repository qualification proves:

- W02-A plans are rerun under the write transaction and stale/forged plans fail closed;
- exact storage keys remain distinct and no case-normalization gains merge authority;
- unrelated durable rows do not consume the bounded relevant snapshot;
- 128+ different canonical verbatim statements cannot exhaust a new independent statement write;
- create preserves candidate authority/provenance fields exactly;
- exact create replay is idempotent only on a full durable-field match and never through a later superseding version;
- exact pending-to-confirmed verbatim promotion creates a new version, links `supersedes_id` and preserves history;
- supersede replay additionally proves the original trusted target link;
- a late legacy mutation failure rolls back earlier writes in the same batch;
- protected writes require exact local-management authority;
- protected value/source provenance never appears in plaintext SQLite fields;
- a late protected encryption failure rolls back earlier writes in the same batch;
- the existing Windows DPAPI/protected-store suites remain green;
- no activation, chat, cloud or public write surface changes are introduced.

`production_activation=false`
