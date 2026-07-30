# Agent 4 A4-06 — append-only timeline and evidence metadata

**Status:** dormant implementation  
**Activation:** explicit caller-driven append only  
**Background work:** none  
**Binary evidence storage:** out of scope

## Purpose

A4-01 through A4-05 emit useful lifecycle events, checkpoint facts, retry
decisions and watchdog outcomes, but the foundation event bus keeps only bounded
process memory. A4-06 adds a durable audit boundary without changing any existing
campaign transition or Agent 3 execution contract.

## Timeline envelope

Each line uses schema:

```text
modelrig-agent4/timeline-entry/v1
```

A line contains:

- campaign id and monotonically increasing timeline sequence;
- entry type (`event` or `evidence`);
- the complete immutable event/evidence item;
- previous entry SHA-256;
- SHA-256 over canonical envelope content.

The first entry uses a 64-zero genesis hash. The per-campaign filename is the
SHA-256 of the campaign id. Reads verify schema, filename binding, sequence,
unique item ids, event sequence, previous hash and content hash before returning
any data.

## Append contract

`JsonlCampaignTimelineStore`:

1. verifies the complete existing timeline;
2. rejects duplicate identities and event-sequence gaps;
3. creates the next hash-chained entry;
4. opens the campaign file in append mode;
5. writes exactly one canonical UTF-8 JSON line;
6. flushes the file descriptor with `fsync` before returning.

Existing lines are never rewritten or deleted. A truncated or partially written
final line fails closed on the next read. Writers are serialized within one
process; multi-process locking and distributed timelines remain deferred.

## Evidence contract

`CampaignEvidence` stores only JSON-safe metadata and optional
`CampaignEvidenceArtifact` references:

- URI;
- SHA-256 digest;
- byte size;
- media type.

Artifact bytes are not copied into the timeline and no URI is fetched. This keeps
A4-06 deterministic and offline while allowing physical-test bundles, logs,
screenshots or reports to be referenced immutably by a future host.

## Durable event bus

`DurableCampaignEventBus` implements the existing record/publish/subscribe shape.
An event is appended and fsynced before callbacks run. After restart, history and
the next event sequence are derived from the verified timeline, so an explicit
host can resume recording without an in-memory sequence reset.

## Safety and deferred work

- no API route, mount, polling loop, timer or automatic ingestion;
- no Agent 3 contract change;
- no cross-process file lock or distributed writer;
- no pruning, compaction or deletion;
- no encryption or binary evidence vault;
- no automatic replay into handlers;
- handler delivery remains synchronous and at-most-once per process invocation.

Those capabilities require separate identities and reviewable contracts.
