# C29-B — Committed-checkpoint liveness recorder

Status: draft, caller-driven composition only, `production_activation=false`.

C29-B records one C29-A runtime liveness witness only after an already-successful C27-C durable SelfState checkpoint.

> **Checkpoint first. Prove liveness second. Never replay the checkpoint because liveness recording failed.**

## Input

The recorder is constructed with:

- one live `ProductionCognitiveSession`;
- one explicit `RuntimeLivenessStore`.

`record_once()` accepts one `RuntimeSelfStateCheckpointResult`.

## Required checkpoint state

C29-B accepts only:

```text
outcome = COMMITTED
self_state_store_write_applied = true
ledger_reanchored = true
plan_ref != null
store_receipt_ref != null
revision_after != null
```

An IDLE or incomplete checkpoint result fails before trusted-clock sampling.

## Exact live-session verification

Before creating any witness, C29-B requires:

- C19 session still open;
- no pending C27-B checkpoint plan;
- no pending C27-B checkpoint states;
- live SelfState revision exactly equal to the committed checkpoint revision.

These checks prove that the in-memory C19 ledger has already accepted the exact C27-C durable commit boundary.

## Trusted time

Only after checkpoint/live-state verification does C29-B sample the existing C18/C11 trusted clock through the live session.

It creates a temporal anchor bound to:

```text
runtime-liveness:<C27-C store receipt ref>
```

No second clock, epoch, timer or cadence source is created.

## Witness source

The C29-A witness `source_ref` is the exact C27-C `store_receipt_ref`.

This binds liveness evidence to the durable checkpoint receipt that made the SelfState revision authoritative.

## Duplicate call

If the liveness store already contains a witness with:

- the same exact SelfState ref/revision;
- the same Self / Person / Person Revision;
- the same C27-C store receipt source;

C29-B returns:

```text
outcome = ALREADY_RECORDED
trusted_clock_sampled = false
liveness_store_write_applied = false
```

The duplicate call does not advance trusted-clock sequence and does not rewrite disk.

## New witness

Otherwise C29-B:

1. samples the existing trusted clock;
2. builds one C29-A witness from the current live SelfState;
3. writes it through `RuntimeLivenessStore.write_next()`;
4. returns `RECORDED`.

## Failure after durable checkpoint

A liveness-store failure occurs **after** C27-C has already committed SelfState.

C29-B therefore fixes:

```text
checkpoint_retry_authority = false
```

It never calls C27-C and never repeats the SelfState store write.

The durable C14 state remains authoritative even when C29-A liveness recording fails.

## Pending state after checkpoint

If a new world/cognitive transition occurs after the checkpoint but before C29-B is called, the session has pending C27-B state again.

C29-B rejects the old checkpoint result before clock sampling or liveness write.

This prevents a witness from pretending the current live state is still exactly the state committed by that earlier checkpoint.

## Authority boundary

C29-B adds no:

- lifecycle hook;
- environment switch;
- scheduler;
- timer;
- thread;
- polling;
- retry;
- route;
- model call;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

It only records liveness for an already-completed durable checkpoint when explicitly called.

## Next slice

C29-C may connect this recorder to the existing C27-F/C27-G successful checkpoint path so every actual COMMITTED checkpoint may optionally produce a liveness witness.

That integration must remain separately gated and must preserve the rule that liveness failure can never replay an already-committed SelfState checkpoint.
