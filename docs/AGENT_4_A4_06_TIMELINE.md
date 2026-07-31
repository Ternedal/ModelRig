# Agent 4 A4-06 — append-only timeline and evidence references

A4-06 adds durable campaign history without changing the caller-driven Agent 4
runtime boundary. It persists existing `CampaignEvent` values as immutable,
hash-chained timeline entries and may bind each entry to zero or more immutable
evidence references.

## Timeline contract

- one filesystem directory is derived from the campaign identity;
- every event is written as one immutable JSON file;
- sequence numbers must be contiguous and start at 1;
- duplicate event identifiers and sequence gaps fail closed;
- every entry after sequence 1 carries the previous entry hash;
- the entry hash covers schema, event content, previous hash and evidence
  references using canonical JSON;
- file names bind the event sequence and event identifier digest;
- listing, verification and replay validate the complete chain before returning
  any entries.

A temporary file is flushed and fsynced before it is linked into the timeline.
The final path is never overwritten. An interrupted temporary file is ignored;
a corrupt final entry fails the entire campaign timeline closed.

## Evidence-reference contract

`CampaignEvidenceReference` stores metadata only:

- stable evidence identifier;
- media type;
- location supplied by the host;
- lowercase SHA-256 digest;
- non-negative byte size;
- optional immutable JSON metadata.

A4-06 does not copy, upload, delete or open the referenced evidence. Binary
evidence storage, retention and authorization remain host responsibilities.

## Explicit operations

`JsonCampaignTimelineStore` exposes only caller-driven operations:

- `append(event, evidence=...)`;
- `list(campaign_id)`;
- `latest(campaign_id)`;
- `verify(campaign_id)`;
- `replay(campaign_id, handler)`.

## Timeline-backed event recorder

`TimelineCampaignEventRecorder` implements the existing `CampaignEventRecorder`
protocol without subscribing to the in-memory bus. It:

- reads the validated durable timeline head;
- assigns the next sequence and deterministic `<campaign_id>:<sequence>` event
  identifier;
- appends the event before returning it;
- restores sequence allocation after creating a new recorder instance;
- serializes concurrent calls made through one recorder;
- may bind evidence explicitly through `record_with_evidence()`.

The recorder performs one durable write only. It does not also publish to a
transient bus, because a dual-write contract would need an explicit recovery and
redelivery model for the case where durable append succeeds and fan-out fails.

No event bus is subscribed automatically. A later composition slice may connect
the durable recorder to transient subscribers, but that integration must define
failure ordering explicitly rather than silently adding side effects.

## Safety boundary

- no API route or runtime mount;
- no background writer, timer or polling loop;
- no automatic event ingestion;
- no network or external-storage call;
- no deletion or mutation API for committed timeline entries;
- one process-local writer lock; distributed writer arbitration is deferred;
- importing `app.agent4` remains side-effect free.

## Validation

The A4-06 cases run through the existing
`tests/workflow_agent4_foundation.py` root entrypoint. They cover ordered append,
evidence round-trip, verification and replay, duplicate/gap rejection, content
tampering, chain and filename rebinding, interrupted temporary files, corrupt
final entries, protocol compatibility, restart-safe sequence allocation,
concurrent callers and fail-closed value validation. No new root test inventory
entry is introduced.
