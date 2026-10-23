# Kaliv Continuum client snapshot contract (prototype v1)

The read-only endpoint `GET /tasks/{task_id}/snapshot` returns JSON from a
single SQLite read transaction. Access requires `Authorization: Bearer <token>`
for an individually registered actor with the task's read ACL; the server
is loopback-only. Unknown, expired, or revoked credentials return 401, and tasks without
read permission return 404. This is **not** a production API.

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

Approval audit metadata is available separately at
`GET /tasks/{task_id}/approvals`. This endpoint requires the actor's
**approve** ACL for that task; read access alone is insufficient. It returns
`{"task_id":"demo-1","approvals":[{"audit_id":1,"approver_id":"alice","executor_id":"worker","capability":"nas.read","revision":2,"issued_at":1000,"expires_at":1300,"consumed_at":null}]}`
(illustrative values). Neither raw approval secrets nor their digests are
returned. Clients must not mistake this history for permission to issue or
execute a new approval.

Clients should treat `presentation` as a rendering hint, not a grant or
permission. `can_request_approval` does not imply that a user is authorized
to approve. No mutation endpoint or trusted approval UI exists yet. Commands
marked `simulated` were **not** executed against external systems.

For Android, Windows and Quest, use the same fields and tolerate unknown
`phase` values. Preserve `revision` to avoid showing stale data. Never
expose the bearer token in URLs or telemetry. The prototype does not
provide login or remote client connectivity. Do not expose the loopback
service on a public network without a separate authenticated gateway.
