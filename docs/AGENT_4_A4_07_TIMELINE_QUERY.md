# Agent 4 A4-07 — verified timeline query paging

A4-07 exposes bounded, read-only pages from the fully verified A4-06 campaign
timeline. It is intended for a later Kaliv/RigGate operator API and UI, where
loading an unbounded campaign history would be unsafe and expensive.

## Query cursor

`CampaignTimelineQueryCursor` is a versioned, JSON-safe position immediately
after one timeline sequence. It binds:

- the campaign identity;
- the contiguous event sequence;
- the SHA-256 hash of the acknowledged entry.

Sequence zero is the explicit genesis cursor and has no entry hash. A cursor for
sequence one or later must bind the exact verified entry hash. Wrong-campaign,
future-sequence and hash-mismatched cursors fail closed.

The query cursor is deliberately distinct from the A4-06 durable delivery cursor.
It does not identify a consumer, acknowledge side effects or persist progress.

## Stable snapshot paging

`CampaignTimelineQueryService.page()` performs one explicit operation:

1. read and fully validate the current timeline through `CampaignTimelineStore`;
2. validate the optional `after` cursor;
3. validate or create a snapshot-head cursor;
4. return at most 1,000 contiguous entries;
5. return start, next and snapshot-head cursors plus `has_more`.

The first page may omit `snapshot_head`; the service then binds the current
verified head. Supplying that returned head to later pages freezes the upper
boundary. Clean append-only growth remains visible to a new query but is excluded
from the existing snapshot.

Old cursors remain valid after clean append-only growth because they bind the
entry at their own sequence. Timeline mutation or corruption still fails through
the underlying A4-06 verification path.

## Safety boundary

- read-only and caller-driven;
- no timeline append, repair, compaction, deletion or truncation;
- no durable offset write or consumer acknowledgement;
- no thread, timer, polling loop, background tailer or automatic replay;
- no API route, runtime mount, network access or Agent 3 contract change;
- no production activation.

## Validation

The existing Agent 4 root workflow gate covers:

- dormant empty queries and cursor serialization;
- bounded contiguous paging;
- stable snapshot behavior across append-only growth;
- clean resume from an old hash-bound cursor;
- campaign, hash, future-sequence and snapshot-boundary rejection;
- cursor lookup and explicit page-limit validation;
- strict cursor value and schema validation.
