# ADR-A4-008 Slice 2 — measured preflight

**Base verified:** `main @ 6b7f5341923ebcf23509331be2b258089f7bbe4f`

**Verdict:** the existing `JsonCampaignRepository` can satisfy Slice 2
without a new ADR. The implementation remains inside the same repository, the
same per-campaign JSON file, the same `RLock`, and the same durable `tempfile`
+ `fsync` + `os.replace` boundary.

## 1. Measured current model

`worker/app/agent4/repository.py` previously wrote
`modelrig-agent4/campaign-envelope/v2`. Its parser required both `record` and
`projection_intents`, while a bare campaign record remained a supported legacy
form.

A4-11 already proves one durable lifecycle:

1. authoritative campaign state and `CampaignProjectionIntent` are written in
   one atomic campaign-envelope replacement;
2. timeline append happens later and is caller-driven;
3. only after the exact event is present does `acknowledge_projection` remove
   the audit intent by `event_id`.

That lifecycle cannot represent external Agent 3 acceptance: a timeline append
is not authoritative evidence that an external side effect occurred.

## 2. Required v3 wire shape

Slice 2 versions the envelope to:

```json
{
  "schema": "modelrig-agent4/campaign-envelope/v3",
  "record": {},
  "projection_intents": [],
  "handoff_intents": []
}
```

All three fields are mandatory for v3. Both intent collections live in the
same campaign file and are included in the same atomic replacement. This is
one persistence model with two typed lifecycles, not a parallel journal.

Writers emit v3 whenever either intent collection is non-empty. Readers
continue accepting:

- v3 envelopes;
- existing v2 envelopes, interpreted as having no handoff intents;
- legacy bare campaign records, interpreted as having neither intent type.

Reading v2 does not rewrite it as a side effect. A dedicated contract test
pins that compatibility.

## 3. Handoff intent value

A durable handoff intent is an immutable, versioned value containing:

- the exact Slice 1 dispatch or signal request;
- deterministic `dispatch_id` or `signal_id` as `intent_id`;
- campaign identity;
- state revision;
- kind: `dispatch` or `signal`;
- phase: `requested` or `acknowledged`;
- an optional matching Slice 1 acknowledgement, including runtime reference
  and evidence pointer where applicable.

The request identity is authoritative. Caller-supplied IDs, campaign IDs,
revisions, acknowledgement types and acknowledgement identities must all match
or fail closed.

New handoff intents may enter the repository only in `requested` phase.
`acknowledged` may be reached only through the handoff-specific acknowledgement
operation. Acknowledged intents remain stored in Slice 2; they are not removed.

## 4. Two acknowledgement rules

### Audit/projection lifecycle

`acknowledge_projection(campaign_id, event_id)` may remove only the matching
entry from `projection_intents`, after the timeline event has been appended or
verified by A4-11's caller-driven reconciler. It preserves the full handoff
collection.

### Handoff lifecycle

`acknowledge_handoff(campaign_id, intent_id, acknowledgement, ...)` may change
only the exact matching handoff from `requested` to `acknowledged` after an
authoritative external acknowledgement has been supplied by a later caller.
It validates dispatch-versus-signal type and deterministic identity.

The acknowledgement and any resulting typed audit intent, such as
`DISPATCH_CONFIRMED`, are persisted in one campaign-envelope replacement. The
repository does not call an executor or append the timeline itself.

Identical acknowledgement retries are idempotent. Conflicting evidence fails
closed. There is deliberately no generic `acknowledge_intent` method.

## 5. Atomicity and crash boundaries

### Requested boundary

The later lifecycle slice will create the resulting campaign state and the
requested handoff value, then call the typed repository write. Slice 2 proves
that the repository exposes only these durable outcomes:

- before `os.replace`: the old complete envelope remains authoritative;
- after `os.replace`: the new campaign record and requested handoff intent are
  both durable;
- no readable state exists with only one half of that write.

### Acknowledgement boundary

For acknowledgement plus its audit intent:

- before `os.replace`: the requested handoff remains and no new confirmation
  audit intent is visible;
- after `os.replace`: the acknowledgement and confirmation audit intent are
  both durable;
- a write failure exposes neither half.

Timeline append and projection acknowledgement remain later caller-driven
A4-11 operations.

## 6. Contract matrix

Slice 2 tests prove:

1. v3 round-trip with record, projection intents and handoff intents;
2. explicit v2 read compatibility without rewrite;
3. legacy bare-record compatibility;
4. requested dispatch and signal intents survive repository restart;
5. deterministic request/revision/campaign binding fails closed;
6. duplicate identical requested intents are idempotent;
7. duplicate identity with conflicting request content fails closed;
8. only the matching dispatch or signal acknowledgement changes phase;
9. acknowledgement retries are idempotent and conflicting evidence is
   rejected;
10. direct insertion of an already acknowledged intent is rejected;
11. a lower record revision cannot make preserved intents appear to come from
    the future;
12. audit acknowledgement cannot remove or modify a handoff intent, including
    when passed a handoff ID — the required sabotage test;
13. handoff acknowledgement preserves unrelated audit and handoff intents;
14. acknowledgement plus its confirmation audit intent is one atomic rewrite;
15. injected failure at requested and acknowledgement `os.replace` boundaries
    leaves the old complete envelope intact;
16. `unknown` is not accepted as an acknowledgement and is never normalized to
    a terminal result;
17. `resource_reconciliation_required` survives every Slice 2 write and
    acknowledgement path;
18. construction/import remains dormant and creates no files or execution.

The complete repository suite, storage-boundary gate, dormant-runtime gate,
CodeQL and authoritative `CURRENT_STATE.md` generation remain mandatory.

## 7. Implementation surface

Implementation files:

- `worker/app/agent4/handoff_persistence.py` — pure durable handoff value;
- `worker/app/agent4/repository.py` — v3 parsing/writing and typed operations;
- focused autodiscovered contract and regression tests;
- generated `CURRENT_STATE.md` update for those test files.

No new repository class, storage root, journal file, database, service or
composition object is introduced.

## 8. Hard exclusions

Slice 2 does not include:

- Agent 3 adapter or executor implementation;
- external dispatch or signal calls;
- runtime composition or protocol wiring;
- scheduler or recovery behavior;
- outcome queries or polling;
- redispatch, cancel, lease acquisition or lease reconstruction;
- routes or write surfaces;
- feature flags or activation;
- automatic timeline reconciliation;
- automatic clearing of `resource_reconciliation_required`;
- conversion of `unknown` to a safe terminal outcome.

## 9. Stop conditions

Stop and request a new architecture decision if implementation requires:

- a second storage class, file or journal;
- weakening v2 or bare-record compatibility;
- a generic acknowledgement path that can mix intent types;
- executor/runtime calls from persistence;
- background processing, polling, scheduling or recovery;
- automatic resource-reconciliation clearing;
- any activation or write-route change.

No stop condition was triggered. The repository carries both lifecycles
atomically while keeping their acknowledgement rules strictly separate.
