# Kaliv Continuum client snapshot contract (prototype v1)

The read-only endpoint `GET /tasks/{task_id}/snapshot` returns JSON from a
single SQLite read transaction. Access requires `Authorization: Bearer <token>`
and the server is loopback-only by default. This is **not** a production API.

Example shape (illustrative values):

```json
{
  "task_id": "demo-1",
  "state": "awaiting_approval",
  "revision": 2,
  "requires_approval": true,
  "presentation": {
    "phase": "approval_required",
    "awaiting_approval": true,
    "terminal": false,
    "can_request_approval": true,
    "is_running": false
  },
  "events": [
    {"revision": 0, "state": "queued"},
    {"revision": 1, "state": "planning"},
    {"revision": 2, "state": "awaiting_approval"}
  ],
  "commands": []
}
```

Clients should treat `presentation` as a rendering hint, not a grant or
permission. `can_request_approval` does not imply that a user is authorized
to approve. No mutation endpoint or trusted approval UI exists yet. Commands
marked `simulated` were **not** executed against external systems.

For Android, Windows and Quest, use the same fields and tolerate unknown
`phase` values. Preserve `revision` to avoid showing stale data. Never
expose the bearer token in URLs or telemetry. Do not expose the loopback
service on a public network without a separate authenticated gateway.
