# C20-A — Provenance-bound epistemic WorldState reducer

Status: draft, Core-only, `production_activation=false`.

C20-A gives Consciousness Core a real, bounded way to learn facts about the
runtime world without making the ThoughtEngine the authority on what is true.

> **Evidence enters with an epistemic label. Core preserves the label.**

## Input contract

A `WorldEvidenceEvent` must carry:

- stable event id;
- subject ref;
- bounded proposition;
- confidence;
- explicit epistemic status;
- one or more unique source refs;
- observed sequence.

Allowed epistemic states are:

```text
observed
reported
inferred
predicted
```

C20-A never derives or upgrades that status from prose, model identity or event
kind.

## Exact binding

Before reduction:

```text
PersistentSelfState.world_state_ref
==
canonical RuntimeWorldState ref
```

A stale or mismatched binding fails closed.

## New evidence

For a previously unseen evidence event:

1. derive a deterministic observation id from the stable evidence event id;
2. append the exact proposition/confidence/status/provenance;
3. advance WorldState revision by exactly one;
4. keep at most 512 observations;
5. when full, evict exactly the oldest observation;
6. advance SelfState revision by exactly one;
7. change only `world_state_ref`.

The reducer verifies that these remain unchanged:

- self_id;
- person_id;
- Person Revision;
- workspace_ref;
- personality_state_ref;
- active goals;
- active intentions;
- affect;
- durable uncertainties;
- last experience ref.

## Replay semantics

While its canonical observation remains inside the bounded live WorldState,
replaying the exact same event id with exact same evidence is idempotent:

```text
world_changed=false
idempotent_replay=true
world revision unchanged
SelfState revision unchanged
no eviction
```

Reusing the same event id with different evidence fails closed. Because the
canonical complete evidence ref is stored in observation provenance, changing
even metadata such as observed sequence, confidence or epistemic status is a
conflict.

This prevents a source from rewriting a retained observation under a previously
accepted event identity.

C20-A does **not** claim unbounded replay memory. Once an observation has been
evicted by the 512-item live-world bound, this transient reducer no longer has
the old event identity available. Durable long-horizon deduplication requires a
separately reviewed evidence ledger rather than pretending transient WorldState
is permanent history.

## Model-derived evidence

C20-A does not forbid a ThoughtProposal ref from being a source.

It does forbid silent epistemic promotion.

For example:

```text
source = thought-proposal:<ref>
status = predicted
confidence = 0.4
```

stays:

```text
predicted / 0.4
```

The reducer does not turn it into `observed` merely because it entered
WorldState.

A later verified observation may add separate evidence with its own event id.

## Retention

RuntimeWorldState remains bounded to 512 observations.

Retention is deterministic insertion order:

```text
new observation
+ existing 512
-> evict oldest one
-> keep 512
```

The transition receipt names any evicted observation id.

## Authority boundary

Every transition receipt fixes:

```text
model_calls=0
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

C20-A adds no:

- model call;
- durable SelfState write;
- Memory 4 write;
- scheduler;
- tool execution;
- Agent 3 execution;
- BodyRig/VoiceRig actuation;
- production event wiring.

## What this unlocks

The live session can now separate two different concepts:

```text
CognitionEvent
    -> something deserves attention

WorldEvidenceEvent
    -> something may enter the epistemic world model
```

That distinction matters.

The next slice can let C19-B accept an atomic pair:

```text
verified world evidence
+
bounded cognition event
```

so a real runtime event can update WorldState first and then be considered by
the next cognitive cycle, without letting the model author its own facts.
