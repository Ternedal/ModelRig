# ADR-A4-008 Slice 4 — Agent 3 adapter proof

**Measured base:** `main @ 92d7a73aa578a3ac26da07feb5e351bd72ae54a7`

**Scope:** the real, dormant receiver-side adapter required by ADR-A4-008.
This slice does not wire the adapter into Agent 4 composition, mount a route,
change a feature flag, or activate unattended execution.

## Implemented ADR and reference architecture

The adapter implements ADR-A4-008 Decisions 1, 3, 5, 6, 7 and 8 against the
existing Agent 3 execution substrate:

- Agent 4 supplies the immutable typed dispatch and signal contracts.
- Agent 3 remains authoritative for execution through the existing
  `Agent3Orchestrator`.
- `AgentRunStore` remains the only persistence boundary.
- The effect registry is a table in the already-selected Agent 3 SQLite
  database, on the same connection and under the same lock as `agent_runs` and
  `agent_events`.
- No second database, journal class, transport model or generic orchestration
  framework is introduced.

The adapter accepts only a server-authored `Agent3CampaignLaunch` from an
injected resolver. It has no client-plan input, provider fallback or direct
tool bypass.

## Dispatch transaction

A new dispatch is accepted under `BEGIN IMMEDIATE`.

The following facts commit together:

1. the deterministic dispatch identity and canonical request hash;
2. one new Agent 3 run;
3. the `run_created` event explaining that run;
4. the binding from dispatch identity to run/runtime reference.

The transaction is deliberately serialized twice:

- `AgentRunStore._lock` serializes users of one store instance;
- SQLite `BEGIN IMMEDIATE` serializes separate `AgentRunStore` instances that
  share the database.

This is required because `AgentRunStore` opens SQLite with
`check_same_thread=False`. Relying only on connection sharing or a read followed
by an insert would leave a race between concurrent callers.

For an existing identity:

- same identity and same request hash returns the original acknowledgement;
- same identity with different request facts fails closed as a conflict;
- a tombstoned identity is rejected permanently;
- a duplicate never starts a second Agent 3 run and never calls `advance`
  again.

The real orchestrator call occurs after the acceptance transaction. A crash
after acceptance therefore leaves an accepted run that can be inspected through
`query_outcome`; it never creates an unregistered side effect.

## Tombstone transaction

`query_outcome` for an unknown dispatch identity opens `BEGIN IMMEDIATE`,
rechecks the registry and inserts the tombstone before returning
`not_dispatched`.

The returned negative is therefore a commitment, not a transient observation.
A delayed original dispatch with that identity is rejected without calling the
launch resolver or Agent 3 executor.

The concurrency sabotage uses two independent stores/connections against the
same SQLite file and issues two simultaneous queries for the same unknown
identity. Both callers must receive `not_dispatched`, while the registry contains
exactly one tombstone row.

## Outcome mapping

The adapter maps only durable Agent 3 facts:

| Durable receiver fact | ADR outcome |
|---|---|
| no registry row, tombstone committed | `not_dispatched` |
| accepted run, no executing step | `accepted` |
| at least one persisted `EXECUTING` step | `running` |
| completed run, no executing step | `completed` + released-resource attestation |
| failed run, no executing step | `failed` + released-resource attestation |
| cancelled run with an executing synchronous step | `unknown` |
| cancelled run after the executing step records `COMPLETED_AFTER_CANCEL` | `failed` + released-resource attestation |
| missing run, malformed run, contradictory effect facts | `unknown` |

A terminal outcome is committed into the effect registry. Once committed, the
attestation remains answerable even if the run row later becomes unavailable.
Missing or contradictory evidence is never converted into a false terminal
answer.

## Signal delivery

Signals use the same deterministic registry:

1. `signal_requested` commits before the orchestrator operation;
2. the real operation is called at most once;
3. `signal_acknowledged` commits only after the operation returns;
4. a retry of an acknowledged signal returns the original acknowledgement;
5. a retry of a requested-but-unacknowledged signal fails closed and does not
   redeliver.

`RESUME` calls the real `Agent3Orchestrator.advance`.
`CANCEL` calls the real `Agent3Orchestrator.cancel`.

## Explicit PAUSING/CANCELLING limitation

### PAUSING

Agent 3 has no safe generic pause primitive. In particular, it cannot suspend a
synchronous in-flight side effect and later resume it from an equivalent
boundary. Slice 4 therefore rejects `PAUSE` fail-closed and writes no false
acknowledgement.

This means the existing Agent 4 `PAUSING` state can remain unresolved when a
future real wiring attempts a pause. Signal-outcome lookup is not part of the
current ADR contract, so the sender must not automatically resend that signal.

### CANCELLING

Agent 3 can persist cancellation, but it cannot physically stop a synchronous
executor call already in progress. While the persisted run is `CANCELLED` and a
step is still `EXECUTING`, the adapter returns `unknown`, not a terminal
resource-release claim.

After the executor returns, Agent 3 records `COMPLETED_AFTER_CANCEL`. The
adapter's full `advance()` caller then reconciles any stale top-level completion
back to `CANCELLED` with a `campaign_late_cancel_reconciled` event before it can
be exposed as a terminal success. Only then does the adapter return terminal
`failed` with released-resource attestation. This preserves the existing Agent
3 late-cancel truth: cancellation does not erase a side effect that actually
completed.

A crash after the cancel operation but before the signal acknowledgement leaves
the signal as durably requested and non-replayable. Slice 4 does not add signal
outcome lookup or automatic signal retry.

## Test obligations

`tests/worker_agent3_campaign_adapter.py` uses the real `AgentRunStore` and
`Agent3Orchestrator` and covers:

- atomic run/event/effect acceptance;
- same-request dispatch idempotence;
- conflicting-request rejection;
- tombstone-before-negative and delayed-original rejection;
- two simultaneous unknown queries on the same identity;
- two simultaneous dispatch calls creating one run and one effective execution;
- completed, failed, waiting-confirmation and running outcome mapping;
- cancel-during-execution remaining `unknown` until the effect finishes;
- signal requested-before-call, acknowledgement and no redelivery;
- fail-closed PAUSE;
- terminal commitment surviving loss of the run row;
- dormant import with no HTTP, provider, subprocess, route or background
  surface.

Repository-wide CI on the exact PR head is authoritative.

## Deliberate exclusions

- no Agent 4 runtime composition change;
- no production mount or route;
- no operator write surface;
- no feature flag or activation;
- no provider SDK or HTTP client;
- no retry loop, timer, polling, task or background worker;
- no fallback/mock executor path;
- no second database, journal or persistence abstraction;
- no automatic redispatch, signal resend, cancel or lease reconstruction;
- no claim of physical-rig validation.

ADR-A4-008 Decision 8 remains the hard activation gate: this code proof is
necessary, but real-adapter physical evidence and Anders' separate activation
decision remain required.
