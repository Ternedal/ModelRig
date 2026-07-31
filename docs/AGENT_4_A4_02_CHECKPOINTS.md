# A4-02 — durable campaign checkpoints

**Status:** immutable local checkpoint store implemented  
**Activation:** explicit lifecycle call only  
**Remote storage:** out of scope

## Envelope

Each checkpoint uses the versioned schema:

```text
modelrig-agent4/checkpoint/v1
```

The envelope binds:

- checkpoint id;
- campaign id;
- campaign revision;
- UTC creation time;
- JSON-safe payload;
- SHA-256 checksum over canonical envelope content.

Checkpoint files are immutable. Reusing the same campaign/checkpoint identity is
rejected rather than overwritten.

## Atomic pointer update

`CampaignCheckpointService.checkpoint(...)` uses this order:

```text
1. write + fsync + atomic-replace immutable checkpoint
2. persist campaign state with checkpoint_id and incremented revision
3. emit CHECKPOINTED event
```

If step 2 fails, the service compensates by deleting the newly written
checkpoint. This avoids a campaign record pointing at data that never became
durable. A process crash between steps 1 and 2 can leave an unreferenced
checkpoint, which is safe and can be garbage-collected later.

## Supported states

Checkpoints are accepted for `RUNNING`, `PAUSING` and `PAUSED` campaigns. They
are rejected for queued, scheduled, cancelling and terminal campaigns.

## Storage boundary

Payloads use the same local filesystem boundary as campaign records. This
contract detects accidental or conflicting content changes. Additional storage
protection and remote backends require a separate design decision.
