# Agent 3 device-bound write approval (T-022 prerequisite)

**Status:** dormant approval boundary delivered for the append-only pilot; no write pilot or normal task routing is activated.

## Why this exists

Agent 3 already paused write steps behind an immutable confirmation digest and a
short TTL. That digest binds the step ID, tool, arguments, risk, sensitivity,
egress, origin, idempotency, conversation and human summary. It did not prove:

- which paired device approved;
- which replan revision was current;
- that an approval could be consumed only once;
- that two concurrent approve clicks could not both reach the same append.

T-022 cannot produce credible physical write evidence without those properties.

## Boundary

The client continues to send only:

```json
{
  "step_id": "...",
  "decision": "approve",
  "digest": "..."
}
```

The approval token is never returned to or accepted from the client.

For an approve request, the authenticated Go backend:

1. reloads the current run and confirmation from the loopback worker;
2. reloads the current replan revision;
3. requires a live `waiting_confirmation` checkpoint for exactly `note_append`;
4. binds the paired device from the Bearer-authenticated request context;
5. signs a random, short-lived token with `KALIV_AGENT3_APPROVAL_SECRET`;
6. injects that token only into the backend-to-worker loopback confirmation.

A deny request is forwarded directly and never mints, verifies or consumes a
token.

## Signed claims

The HMAC token binds:

- random nonce;
- authenticated device ID;
- run ID and step ID;
- tool (`note_append` only);
- SHA-256 of the exact UTF-8 `text` payload;
- immutable confirmation digest, which independently binds the full step and
  argument object;
- current plan revision;
- issue and expiry timestamps.

The pilot accepts exactly one non-empty `text` argument of at most 10,000
characters. Generic JSON hashing is deliberately avoided because runtimes can
serialize numbers and escaping differently. Go and Python therefore hash the
same executable string bytes, including non-ASCII and HTML-like text.

Its expiry is at most two minutes and can never outlive the existing confirmation
card.

## Worker enforcement

When `KALIV_AGENT3_APPROVAL_REQUIRED=1`, approve without a token fails closed.
A supplied token is always verified, even while the migration switch is off.
The worker checks signature, time, action, exact text hash, digest, revision and
the current waiting run before any write.

Before the orchestrator may execute, SQLite atomically consumes:

- the token nonce; and
- an immutable action key derived from run, step, confirmation digest and plan
  revision.

The second uniqueness constraint matters: two simultaneous approve requests may
receive different random tokens, but only one can authorize the same append.

The run event ledger receives a content-free `approval_consumed` event followed
by the existing `confirmation_approved`, `policy_decision`, `step_started` and
`step_succeeded` events. Attribution includes only device ID, timestamps,
revision and hashes; raw token, nonce and note text are never written to the
event ledger.

## Configuration

Backend and worker must receive the same random secret of at least 32 bytes:

```text
KALIV_AGENT3_APPROVAL_SECRET=<random shared secret>
```

Enforcement is dormant by default:

```text
KALIV_AGENT3_APPROVAL_REQUIRED=1
```

The physical T-022 pilot must set both values. If enforcement is on and the
secret is absent or inconsistent, approval fails before the worker executes.

The approval-use database defaults to `kaliv-agent3-approvals.db` and may be
placed explicitly with `KALIV_AGENT3_APPROVAL_DB`.

## Deliberate limits

This slice:

- authorizes only `note_append`;
- does not expose delete, model-pull, admin or destructive writes;
- does not activate Agent 3 task routing;
- does not merge or run the 20-case physical write pilot;
- keeps the legacy direct developer confirmation available only while
  `KALIV_AGENT3_APPROVAL_REQUIRED` is off.

## Remaining T-022 work

After T-020/T-021 physical evidence and review:

1. enable the approval requirement on the exact candidate;
2. run 20 bounded marker appends with visible preview and explicit confirmation;
3. test denial, timeout, changed args, stale revision, replay and concurrent
   approval;
4. compare the exact note marker with `approval_consumed`,
   `confirmation_approved`, `policy_decision`, `step_started`, `step_succeeded`
   and `run_completed`;
5. verify stop/retry/replan cannot duplicate the append;
6. publish a dated, version- and code-bound physical report before any promotion.
