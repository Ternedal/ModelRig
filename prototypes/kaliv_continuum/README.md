# Kaliv Continuum prototype — status and security gates

**Isolated prototype only.** No production wiring, real external actions,
Android deployment or public/LAN exposure. Keep draft PR separate from main.

## Implemented

- Versioned task state transitions, SQLite persistence and event history.
- Scoped expiring single-use approval grants, transactional execution
  reservation and command outbox (simulation only).
- Bounded Swarm DAG planner and deny-by-default dry-run worker.
- Per-actor read credentials (random tokens, SHA-256 digests in SQLite,
  individual revocation) and deny-by-default task ACLs.
- Loopback read-only HTTP API with per-task authorization on all routes:
  `GET /tasks/{id}`, `GET /tasks/{id}/events`,
  `GET /tasks/{id}/commands`, `GET /tasks/{id}/snapshot`.
- Transaction-consistent snapshots and presentation hints.
  See [CLIENT_CONTRACT.md](CLIENT_CONTRACT.md).
- Isolated Python 3.11/3.12 CI workflow and tests.

## Security and production blockers

1. **Identity provisioning and ACL grants are administrative Python calls,**
   not trusted enrollment or a user login flow. The API validates registered
   bearer credentials and checks ACLs but is not a full identity provider.
2. **Approval grant issuance is not trusted.** No authenticated approval UI,
   policy-version binding or authority integration exists. Never connect
   real execution capabilities.
3. The HTTP server has no TLS, quotas, request-size bounds, structured
   auditing, or managed lifecycle. Keep loopback-only.
4. SQLite has no configured encryption-at-rest, retention policy, or
   backup/recovery procedures. Restrict local filesystem permissions.
5. The outbox is **dry-run only** and does not prove exactly-once external
   execution, leases, crash recovery or dispatch idempotency.
6. Capability allowlists are not a substitute for `kaliv-capability/v2`.
7. Presentation flags are **UI hints**, not authorization decisions.
8. No write API. Do not infer production readiness from green CI.

## Run isolated tests

```bash
cd prototypes/kaliv_continuum
python -m unittest discover -p 'test_*.py' -v
```

## Local-only smoke test

Run in a disposable directory. This provisions one test actor, grants read
access to one task, and prints a **secret** token. Never commit the token.

```bash
cd prototypes/kaliv_continuum
python - <<'PY'
from task_store import TaskStore
from task_access import TaskAccess
from read_identity import ReadIdentity
db = "demo.sqlite"
TaskStore(db).create("demo")
TaskAccess(db).grant("demo", "local-test", "read")
print("TEST TOKEN (keep private):", ReadIdentity(db).issue("local-test"))
PY
python read_api.py demo.sqlite
```

From a separate terminal, use the printed token:

```bash
curl -H "Authorization: Bearer YOUR_TEST_TOKEN" \
  http://127.0.0.1:8769/tasks/demo/snapshot
```

An unknown or revoked token receives HTTP 401; an authenticated actor
without the task's read ACL receives HTTP 404. No POST/PATCH/DELETE routes.

## Next gate

Trusted provisioning, per-task policy audit, authorized approval issuance,
and bounded real worker dispatch must be independently reviewed before
any production integration. Keep mutating endpoints disabled.
