# Agent 4 A4-19 — campaign-list snapshot paging

## Problem

A4-14 exposed a bounded campaign list with status filters and `limit`, but no
cursor. Android could show the first page, yet any local offset would race
concurrent campaign creation, lifecycle state changes or timeline/evidence
updates and could silently duplicate, lose or mix entries.

A4-19 adds server-verified paging. The server keeps no paging session; all
continuation authority travels in hash-bound cursors.

## Cursor contract

Schema:

```text
modelrig-agent4/campaign-list-query-cursor/v1
```

Each cursor binds:

- the canonical sorted status filter;
- zero-based consumed position;
- total records in the snapshot;
- last campaign ID at that position;
- SHA-256 of the complete filtered, newest-first canonical snapshot.

The snapshot digest covers both each canonical campaign record and the exact
verified summary fields rendered in the list:

- timeline entry count;
- event entry count;
- evidence entry count;
- latest timeline head hash.

The service computes each campaign overview once per request and uses that same
verified value for both the response and the snapshot digest. A timeline or
evidence change between pages therefore invalidates the continuation even when
the campaign record itself is unchanged.

The first response includes:

```json
{
  "campaigns": [],
  "start_cursor": {},
  "next_cursor": {},
  "head_cursor": {},
  "has_more": false
}
```

`campaigns` remains in the same top-level location for backward wire
compatibility. Existing clients can ignore the additive cursor fields.

## Continuation

The next request must send both:

```text
after=<previous next_cursor>
snapshot_head=<first page head_cursor>
```

The server recomputes the filtered snapshot and rejects the request if:

- schema or cursor shape is unknown;
- status filters differ;
- a campaign record or rendered summary changed;
- snapshot hash or total changed;
- position is outside the snapshot;
- last campaign ID does not match the position;
- `after` is supplied without `snapshot_head`, or vice versa.

A changed snapshot returns the existing redacted operator `422` response. The
client must refresh from page one; it must not merge a stale continuation.

## Android

`CampaignCursor` is a separate opaque type from timeline/evidence cursors.
`listCampaigns` requires both continuation cursors together and validates the
returned schema, filters, bounds, identity and snapshot hash shape.

The Compose list:

- loads at most 25 campaigns per page;
- sends exact `after` + `snapshot_head` on `Hent næste kampagneside`;
- requires the returned start cursor to equal the requested next cursor;
- requires the snapshot head to stay unchanged;
- rejects duplicate campaign IDs;
- clears previously rendered campaigns on auth, grant, network or protocol
  failure.

## Safety

A4-19 adds no mutation, server-side session, polling, lifecycle control or
production activation. It changes only GET response metadata and client paging.
`production_activation=false`.

## Validation

Tests cover:

- multi-page newest-first traversal without duplicates or loss;
- stable empty snapshots;
- canonical filter ordering and binding;
- campaign-record changes between pages;
- timeline/evidence summary changes between pages;
- missing or malformed summaries;
- tampered position, identity, digest and schema;
- additive HTTP envelope and redacted 422 errors;
- Android opaque cursor round-trip;
- campaign identity merge policy;
- cross-layer cursor-schema parity and absence of local offset fallback.
