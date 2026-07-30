# A4-07 verified timeline replay and paging

A4-07 adds a caller-driven read/replay layer above the A4-06 append-only timeline.
It does not change timeline bytes, lifecycle state, Agent 3 contracts or runtime
activation.

## Contract

- every cursor is bound to one campaign, one timeline sequence and the exact
  SHA-256 content hash at that position;
- sequence `0` is the genesis cursor and must use `GENESIS_HASH`;
- an old cursor remains valid after clean appends because the verified prefix is
  unchanged;
- wrong-campaign, future-sequence and hash-mismatched cursors fail closed;
- paging reads one fully verified snapshot and returns start, next and head cursors;
- synchronous replay advances its returned cursor only after the handler accepts
  an entry;
- handler failure exposes the failed entry and the last successful cursor so a
  caller can resume without silently skipping data;
- appends performed during replay are not included in the current snapshot and
  appear on the next explicit call.

## Limits

`limit` and `max_entries` are explicitly bounded to `1..1000`. A4-07 does not
provide filtering, background tailing, durable consumer offsets, distributed
leases, API routes or automatic callback retries.

## Safety boundary

Construction performs no I/O. Every operation is an explicit caller action and
A4-06 verifies the entire timeline before A4-07 returns or replays any entry.
A4-07 never writes, truncates, compacts, deletes or repairs timeline data.
