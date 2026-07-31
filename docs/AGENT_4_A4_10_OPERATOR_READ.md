# Agent 4 A4-10 — bounded operator read model

A4-10 adds one dormant, transport-independent read boundary over the explicitly
composed B-reference runtime. It is intended for a later Kaliv or RigGate adapter,
but it mounts no API and makes no authentication or transport decision.

## Campaign overviews

`Agent4OperatorReadService` exposes bounded newest-first campaign summaries.
Each `Agent4CampaignOverview` contains:

- the durable campaign record and lifecycle status;
- the verified timeline entry count;
- the number of immutable evidence references;
- the latest verified timeline hash.

`list_campaigns()` accepts one status or an iterable of statuses and returns at
most 1,000 campaigns. Filtering is performed before the limit is applied. The
regression contract explicitly verifies that, after `campaign-a` is dispatched,
`statuses="queued"` returns only `campaign-b`.

## Timeline pages

Timeline paging delegates directly to B's `CampaignTimelineQueryService` and
therefore reuses its versioned, hash-bound cursors and stable snapshot-head
semantics. A4-10 introduces no second page, cursor or offset format.

## Safety boundary

- read-only, dormant and caller-driven;
- no lifecycle mutation, delivery acknowledgement or progress write;
- no timeline append, repair, compaction, deletion or truncation;
- no API route, socket, authentication decision or network request;
- no thread, timer, polling loop, background tailer or automatic refresh;
- no Agent 3 contract change or production activation.

## Validation

The shared Agent 4 root gate covers:

- dormant construction over the exact composed scheduler, timeline and query;
- verified campaign counters and latest-head reporting;
- newest-first bounds and the queued-status regression;
- stable snapshot paging through B's hash-bound query cursors;
- unknown campaigns, invalid statuses and invalid limits.
