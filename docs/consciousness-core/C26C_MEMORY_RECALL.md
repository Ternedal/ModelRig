# C26-C — Privacy-safe Memory 4 recall attention

Status: draft, event-admission only, `production_activation=false`.

C26-C connects the existing C7 / Memory 4 read path to the C18 pending event queue.

It does **not** copy recalled memory text into a CognitionEvent.

> **Memory content may inform cognition. Attention metadata must not become a second memory store.**

## Input authority

C26-C accepts only an existing `MemoryContextSnapshot` produced by
`Memory4ExperienceBridge.recall()`.

That snapshot is already constrained to:

```text
authority = reference_data
sent_to_model = false
production_activation = false
```

Before any event admission, C26-C revalidates:

- SHA-256 of the exact context bytes;
- character count;
- UTF-8 byte count;
- canonical `memory4-context:<sha256>` source ref;
- consistency between empty context and empty included-id set.

Invalid or tampered snapshots fail closed.

## Empty recall

The Memory 4 compiler deliberately returns a truly empty result when nothing is
included:

```text
context = ""
included_ids = []
```

C26-C maps that to:

```text
cognition_event = null
clock_sample_ref = null
supervisor revision unchanged
```

No C18 clock sample is consumed for an empty recall.

## Non-empty recall

A non-empty validated snapshot obtains one trusted C18 runtime clock sample.

C26-C then creates one:

```text
kind = memory_recall
salience = 0.90
observed_sequence = ClockSample.sampled_sequence
```

The event source ref is a canonical digest over:

- the canonical MemoryContextSnapshot ref;
- the exact trusted ClockSample ref.

The event summary contains only:

- number of included reference-data items;
- local/cloud target;
- an explicit statement that recalled text and ids remain outside the event.

It contains no recalled memory text and no individual memory ids.

## Session admission

`ProductionCognitiveSession.submit_memory_recall()` is the only C26-C queue
side effect.

Flow:

```text
MemoryContextSnapshot
-> integrity validation
-> empty?
   yes -> no-op receipt
   no  -> trusted C18 ClockSample
       -> MemoryRecallPlan
       -> existing C18 queue
```

Live C19 state is not modified:

- SelfState unchanged;
- WorldState unchanged;
- CognitiveWorkspace unchanged;
- PersonalitySnapshot unchanged;
- completed cycle count unchanged;
- response-guidance mailbox unchanged.

## Replay behavior

The session keeps a bounded process-local replay ledger keyed by canonical
MemoryContextSnapshot ref.

The ledger stores only:

- hashes;
- count;
- event metadata;
- clock binding.

It stores no recalled text or memory ids.

Re-admitting the exact same snapshot reuses the first event and first trusted
clock binding.

Therefore exact replay:

- consumes no new clock sample;
- creates no second C18 event;
- does not advance supervisor revision.

The ledger is cleared at session close.

## C25 relationship

The default C25-A policy uses:

```text
memory_recall_min_salience = 0.85
```

C26-C uses fixed Core salience `0.90`.

Therefore with C25-A/B/C separately enabled, free budget and no cooldown:

```text
Memory 4 recall
-> verified non-empty snapshot
-> C26-C memory_recall event
-> C18 pending queue
-> existing scheduler cadence
-> C25-C
-> C25-B
-> C25-A eligible
-> exact-event cognitive step
```

C26-C does not bypass anti-hitchhike, cooldown, rolling budget, supervisor pacing
or single-flight.

## Privacy boundary

C26-C receipts/events expose no:

- memory context text;
- raw memory values;
- individual included memory ids;
- Memory 4 storage records.

Only count + cryptographic references cross into attention metadata.

## Authority boundary

C26-C adds no:

- model call;
- automatic Memory 4 query;
- Memory 4 write;
- scheduler;
- thread;
- timer;
- polling loop;
- retry;
- SelfStateStore write;
- Agent 3/tool execution;
- BodyRig actuation;
- VoiceRig actuation.

All plans, receipts and events retain:

```text
production_activation=false
```

C26-C is the third authoritative non-user attention source after C26-A
wake-followup and C26-B prediction mismatch.
