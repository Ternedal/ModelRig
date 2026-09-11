# Memory 4.0 W02-B — guarded persistence and review handoff

Status: implementation candidate; default-off and not wired into normal chat.

W02-A landed through #1206 and owns the storage-neutral, model-independent
candidate consolidation plan. W02-B composes that plan with the existing Memory 3
legacy/protected stores without granting the planner correction authority.

## Authority boundary

The W02-A planner may emit `create`, `dedupe`, `skip` and one deliberately narrow
`supersede` proposal for exact pending -> confirmed promotion of the same
canonical verbatim statement. W02-B does **not** execute that supersede proposal.
It converts it into a review handoff bound to the current durable row id and
`updated_at` token.

Actual correction/version/supersede remains the existing explicit trusted
local-management path. W02-B never calls `MemoryStore.correct()` or
`ProtectedMemoryWriter.correct()`.

A persistence decision is not trusted merely because it is a typed Python
object. Apply revalidates the candidate through the landed W02-A authority
contract. In addition, secret candidates can never gain automatic `create` or
`reuse` authority even if an internal caller hand-constructs a persistence
decision and bypasses preparation.

## Persistence preparation

Before any write, W02-B reads current durable state again and transforms the
neutral plan into one of four persistence outcomes:

- `create` — a still-safe new candidate may be persisted;
- `reuse` — an exact durable value is bound by id + `updated_at` and reused;
- `review` — durable meaning, authority or concurrency state requires an explicit
  trusted decision;
- `skip` — no storage action is permitted or required.

A neutral `skip` is resolved before any persistence-slot read. In particular,
secret candidates do not trigger an unnecessary `LOCAL_MANAGEMENT` read or
protected-field decryption pass merely to be skipped.

For structured pending candidates, a different value under one reviewed durable
subject/predicate is a review handoff, not an automatic second fact and not a
correction. The handoff carries the exact reviewed row id and `updated_at` token.
Ambiguous reviewed state fails closed.

W02-B also evaluates the whole neutral action batch before any write. Multiple
non-verbatim candidates for the same structured subject/predicate with different
values or metadata become `review`/non-mutating outcomes. Apply order therefore
cannot decide which candidate happens to become durable first. Exact duplicate
batch entries remain non-mutating duplicates rather than conflicts.

Confirmed W01 verbatim statements remain independent notes. A distinct statement
may be created even when other `user / verbatim_user_statement` rows exist; an
exact statement is reused. A concurrent exact insert invalidates a planned
create.

## Apply boundary

`create` and `reuse` are revalidated immediately before apply:

- reuse requires the exact durable id, unchanged `updated_at`, value, kind and
  non-weaker sensitivity/review authority;
- an expired exact row is never treated as a valid reuse target; it fails closed
  to review during persistence preparation;
- structured create requires the slot still to be empty;
- verbatim create permits other independent verbatim notes but refuses an exact
  duplicate that appeared after planning;
- review/skip never mutate storage.

Legacy persistence reuses `MemoryStore.create()`. Protected persistence reuses
`ProtectedMemoryReader`/`ProtectedMemoryWriter` and requires exact
`LOCAL_MANAGEMENT` access for both read and create. Sensitive protection remains
inside the existing protected writer.

## Deliberately absent

W02-B adds no model/LLM/network call, no HTTP route, no automatic completed-turn
write hook, no `/api/v1/chat` write integration, no background scheduler, no
Agent 3 activation, no private-cloud grant, no delete authority and no production
activation.

`production_activation=false`.
