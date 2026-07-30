# Agent 4 A4-08 — bounded operator read model

A4-08 adds one host-neutral read boundary over the explicitly composed Agent 4
runtime. It is the transport-independent contract a later Kaliv or RigGate adapter
can call before any HTTP route, authentication scheme or recurring runtime loop is
chosen.

## Delivered contract

`Agent4OperatorReadService` exposes three explicit reads:

1. `campaign(campaign_id)` returns the immutable campaign record together with
   verified timeline, event and evidence counts plus the current timeline head
   hash;
2. `list_campaigns(...)` returns newest campaigns first, optionally filtered by
   lifecycle status and bounded to 1..1,000 results;
3. `timeline_page(...)` returns at most 1..1,000 fully verified timeline entries
   after a caller-provided sequence.

The service is part of `Agent4RuntimeContext`, and it shares the exact scheduler
and timeline instances composed by `compose_agent4_runtime(...)`.

## Stable timeline snapshots

The first timeline read may omit `snapshot_sequence`. A4-08 then binds the result
to the current verified timeline head and returns that sequence. Reusing it on
later calls keeps paging stable while clean append-only growth continues:

- entries appended after the snapshot are not included;
- a new explicit call without the old snapshot sees the newer head;
- a snapshot beyond the verified head is rejected;
- an `after_sequence` beyond the snapshot is rejected;
- every page is read only after the complete JSONL hash chain has verified.

This is a read snapshot, not a durable consumer acknowledgement. It performs no
handler side effect, writes no cursor and makes no exactly-once claim.

## Safety boundary

A4-08 remains dormant and caller-driven:

- no API route, socket, authentication decision or network request;
- no thread, timer, polling loop, background tailer or automatic refresh;
- no lifecycle command, dispatch, pause, resume, cancellation or retry action;
- no timeline append, repair, compaction, deletion or truncation;
- no Agent 3 contract change or production activation;
- constructing the runtime still creates no directory or file.

An operator command facade, transport adapter and recurring host loop are separate
future decisions. They must preserve the existing explicit-call and fail-closed
contracts.

## Contract coverage

The shared Agent 4 timeline gate covers:

- dormant construction and shared object identity;
- verified campaign counters and timeline head hashes;
- newest-first bounded lists and lifecycle-status filters;
- stable snapshot paging while clean appends continue;
- unknown campaign rejection;
- invalid list, page and snapshot bounds;
- public package exports through `app.agent4`.
