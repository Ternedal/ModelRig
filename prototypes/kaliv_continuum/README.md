# Kaliv Continuum prototype — status and security gates

**Isolated prototype only.** No ModelRig production wiring, external tool
execution, Android deployment, or LAN/public exposure. Keep the draft PR
separate from protected `main`.

## Implemented

- State transitions, optimistic task revisions, SQLite persistence and events.
- Scoped expiring one-use approval grants; `reserve_execution()` consumes
  a matching grant, transitions the task and writes a command outbox record
  in one SQLite transaction.
- Bounded Swarm DAG planning, capability-filtered simulation, and a
  deny-by-default dry-run worker that records receipts without external effects.
- Read-only authenticated loopback HTTP API:
  `GET /tasks/{id}`, `GET /tasks/{id}/events`,
  `GET /tasks/{id}/commands`, `GET /tasks/{id}/snapshot`.
- Transaction-consistent snapshots and client presentation hints.
  See [CLIENT_CONTRACT.md](CLIENT_CONTRACT.md).
- Isolated Python 3.11/3.12 CI workflow and unit/integration tests.

## Security and production blockers

1. **Grant issuance is not trusted yet.** `ApprovalStore.issue()` can be
   called directly by code with database access. There is no authenticated
   approval UI, actor identity, policy-version binding, or authorization
   gateway. Do not connect real capabilities.
2. `transition(..., verified_approval=True)` is a pure internal helper;
   its flag is not proof of authorization. The trusted path is the atomic
   store reservation, and only after grant issuance is properly secured.
3. No per-task ownership/tenant isolation. Anyone with the read bearer
   token can read all known task IDs. Never expose the service beyond
   loopback without a gateway enforcing actor and task authorization.
4. SQLite has no configured encryption-at-rest, retention policy or
   backup/recovery procedures. Use a private data directory.
5. The HTTP server has no TLS, rate limits, health checks or lifecycle
   management. It is local-only.
6. The outbox dry-run receipts demonstrate transactional deduplication
   **inside SQLite only**. They do not prove exactly-once external effects,
   retries, leases, or crash-safe real dispatch.
7. Swarm capability allowlists are prototype checks, not a substitute
   for the existing `kaliv-capability/v2` policy authority.
8. `presentation.can_request_approval` is a UI hint, **not** permission
   to issue or approve a grant.
9. No write API exists. Do not infer production readiness from green
   prototype CI.

## Run isolated tests

```bash
cd prototypes/kaliv_continuum
python -m unittest discover -p 'test_*.py' -v
```

## Local-only smoke test

Use a disposable SQLite file and a random token; do not reuse production
credentials. The API cannot create tasks.

```bash
cd prototypes/kaliv_continuum
python -c "from task_store import TaskStore; TaskStore('demo.sqlite').create('demo')"
export KALIV_CONTINUUM_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python read_api.py demo.sqlite
```

In another terminal, pass the same token in an Authorization header to
`http://127.0.0.1:8769/tasks/demo/snapshot`.

## Next gate

Add trusted policy-authorized grant issuance and per-actor task access,
then a properly bounded and auditable worker dispatch protocol. Keep all
mutating endpoints and production integrations disabled until those
controls have independent tests and review.
