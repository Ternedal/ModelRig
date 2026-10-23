# Continuum prototype integration and security checklist

This prototype is NOT a production API and must not be exposed to LAN or internet.

## What exists
- Pure Python task state transitions.
- SQLite task persistence and event history.
- Loopback-only authenticated read API for GET /tasks/{id} and GET /tasks/{id}/events.
- Unit test sources for state transitions and persistence.

## Known blockers before production
1. Current transition() accepts any nonempty approval_token. This is a placeholder, not authentication. Do not connect write capabilities to it. Replace with signed, scoped, expiring, one-use approval grants bound to actor, task, action, revision and policy version.
2. approved boolean currently persists across transitions; scope and expiration are not represented. Do not use it for authorization.
3. No ownership/tenant isolation; a holder of the read API token can read any task ID. Add authenticated actor identity and per-task authorization.
4. SQLite persistence has no encrypted-at-rest or retention policy. Use an explicit private data directory with restrictive permissions and backups.
5. Read API has no TLS, request quotas, lifecycle management, health checks or production deployment. Loopback only.
6. No full end-to-end test evidence. Run tests in a clean environment before any promotion.
7. Existing ModelRig capability descriptor authority is kaliv-capability/v2; do not introduce a parallel permission source. Map the future Nexus registry through that authority.
8. Event log records state transitions only; not yet a durable execution/outbox system. Do not claim exactly-once tool execution.
9. The API intentionally has no POST/PATCH/DELETE endpoints.

## Run prototype tests
From the repository root:

```bash
cd prototypes/kaliv_continuum
python -m unittest discover -p 'test_*.py' -v
```

## Local-only smoke test
Create a disposable SQLite file and a random bearer token. Never reuse production credentials. The API intentionally cannot create tasks.

```bash
cd prototypes/kaliv_continuum
python -c "from task_store import TaskStore; TaskStore('demo.sqlite').create('demo')"
export KALIV_CONTINUUM_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python read_api.py demo.sqlite
```

In a separate terminal with the same token, request GET http://127.0.0.1:8769/tasks/demo using Authorization: Bearer <token>.

## Next implementation gate
Implement verified approval grants, per-actor task authorization and durable idempotent command handling before exposing write operations. Keep default-off behind a feature flag and preserve current release gates.
