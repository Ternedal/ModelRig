# Agent 4 A4-17 — Kaliv Android read client

## Scope of this slice

This branch implements the first usable Android product path for the Agent 4
operator surface:

```text
Kaliv Control Center
  → authenticated ModelRig backend
  → agent4:read grant
  → loopback worker
  → canonical Agent 4 read services
```

The screen is opened from Control Center and is visibly read-only. It contains
no lifecycle or campaign mutation control.

## Typed transport

`Agent4OperatorClient` supports only GET operations:

- campaign list with validated status filters and bounded limit;
- campaign detail;
- timeline pages;
- evidence pages;
- evidence verification;
- direct evidence lookup.

Successful responses must use:

```text
Content-Type: application/vnd.modelrig.agent4.operator+json
schema: modelrig-agent4/operator-api/v1
```

Unknown media types, schemas, campaign states, missing required fields and
malformed hashes fail closed as protocol errors.

## Authorization states

The client distinguishes:

- `401` — pairing/credential must be renewed;
- exact `403 agent4 read grant required` — paired but locked;
- `404` — requested campaign/evidence does not exist;
- `405` or `422` — request rejected;
- `503` or network failure — temporarily unavailable;
- malformed success response — protocol failure.

The UI never converts these states into success.

## Cursor and canonical data boundary

Timeline and evidence cursors are returned as opaque values. The caller can only
pass them back to the client as `after` or `snapshot_head`; it cannot edit cursor
fields through a typed mutation API.

Campaign records, timeline entries and evidence records remain server-owned
canonical JSON. The Android layer wraps them for display and extracts only the
small identity/status/count fields needed by the UI. It does not create a
parallel Agent 4 domain model.

Timeline and evidence paging are bounded and snapshot-bound: every subsequent
page sends both the previous `next_cursor` and the first page's `head_cursor`.
The UI therefore cannot silently mix entries from different logical snapshots.

## Stale-data protection

The list and detail screens clear previously rendered privileged data before
every refresh and before evaluating a new auth/network result. A revoke, invalid
token, protocol failure or network error therefore replaces campaign, timeline
and evidence data with a locked or error state rather than leaving stale data
visible.

The OkHttp client uses no-cache/no-store requests and no direct worker address.

## Current UI

Control Center exposes:

```text
Agent 4 · read-only
```

The campaign list shows:

- campaign name and canonical ID;
- status;
- timeline/event/evidence counts;
- latest timeline hash when present;
- explicit loading, pairing-required, grant-required, empty, unavailable and
  protocol-error states.

The campaign detail view shows:

- canonical workflow, priority, attempt, revision and timestamps;
- evidence-chain verification and bound hashes;
- timeline entries with bounded `Hent næste` paging;
- evidence records with bounded `Hent næste` paging;
- immediate locked/error replacement if authorization or protocol validation
  fails during initial load or later paging.

## Non-goals

This slice does not add:

- grant administration in Android;
- submit, dispatch, pause, resume, cancel, retry or signal;
- direct worker networking;
- cached privileged records after revoke;
- Agent 4 production activation or unattended orchestration.

`production_activation` remains `false`.

## Validation

MockWebServer contracts cover:

- backend URL, Bearer and media type headers;
- deterministic status filtering;
- typed campaign parsing;
- opaque cursor round-trip;
- encoded dynamic path segments;
- 401/403/404/422/503 classification;
- unknown media type/schema/status rejection;
- invalid input rejection before network use.

Presentation contracts additionally cover:

- canonical campaign-record parsing;
- timeline-entry schema and hash parsing;
- evidence-record schema and hash parsing;
- fail-closed rejection of unknown schemas and malformed hashes.
