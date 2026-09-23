# Consciousness Core C7 — ExperienceCandidate and Memory 4 bridge

Status: stacked implementation over C6. No parallel memory store. No production activation.

Issue: #1617.

## Core rule

Consciousness Core may create a non-durable `ExperienceCandidate`.

Memory 4 remains the only durable autobiographical-memory authority.

```text
cognitive cycle
  -> ExperienceCandidate
  -> C7 handoff decision
       |
       +-> structured/inferred meaning -> trusted review required
       +-> secret -> blocked
       +-> exact user-explicit completed turn
             -> existing Memory 4 W01/W02 authority
             -> durable receipt reference
```

C7 never serializes Core/model-authored semantics into fake user text.

## Read path

C7 consumes the existing Memory 4 `context_for_turn` service through injection.

It verifies:

- returned object is the existing Memory 4 result type;
- receipt SHA-256 matches exact context bytes;
- character and byte counts match;
- the service says the context has not already been sent to a model.

The resulting `MemoryContextSnapshot` is explicitly marked:

```text
authority = reference_data
```

It is not a WorldState mutation or system instruction.

## Write path

The only automatic handoff C7 permits is:

- `kind = USER_STATED_FACT`;
- `provenance_kind = user_explicit`;
- candidate is bound to an exact `completed_turn_source_ref`;
- sensitivity is not secret;
- the supplied `CompletedMemoryTurn.source_ref` matches exactly.

Even then, C7 does **not** persist the ExperienceCandidate.

It submits the original `CompletedMemoryTurn` to the existing
`MemoryCompletedTurnWriteService`, where W01 extraction and W02 durable authority
continue to decide what, if anything, is stored.

All structured Core/model meaning such as prediction errors, action outcomes,
relationship interpretation or personality evidence remains
`trusted_review_required` until a separate trusted semantic review boundary
exists.

## Secret handling

A secret ExperienceCandidate is `blocked_secret` at the C7 handoff boundary.

Existing Memory 4 secret protections remain independently authoritative.

## No competing store

C7 contains no SQLite import, MemoryStore, retry queue, scheduler or background
writer.

A Memory 4 failure is surfaced to the caller. C7 does not launch hidden retry
work.

## Provenance

ExperienceCandidate retains cognitive-cycle provenance separately from durable
Memory 4 ids.

A successful write handoff produces `MemoryDurableReceiptRef`, which carries
only the existing Memory 4 receipt schema, counts and ids plus the source
ExperienceCandidate reference.

It does not copy protected memory values back into Consciousness Core state.

## Authority boundaries

C7 has no authority to:

- create durable memory rows directly;
- mark inferred semantics confirmed;
- delete/correct/supersede memory directly;
- change privacy classification;
- activate personality;
- mutate Person/Profile;
- call Agent 3/tools;
- create background retries;
- activate production.

`production_activation=false`.
