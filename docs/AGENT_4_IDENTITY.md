# Agent 4 identity and ownership contract

**Owner:** Sol  
**Runtime status:** dormant and caller-driven  
**Authoritative branch prefix:** `agent/a4-*`

## Ownership

Sol owns:

- `worker/app/agent4/**`;
- Agent 4-specific tests and support cases;
- `agent4/**` and `docs/AGENT_4_*` contracts.

Host/backend/client integration outside those paths remains Claude-owned. Shared
integration boundaries and `HANDOFF.md` require parity evidence and coordination.

## Stable work identities

| ID | Scope |
|---|---|
| `A4-01` | foundation, lifecycle and startup recovery |
| `A4-02` | durable checkpoints |
| `A4-03` | resource leases and scheduler admission |
| `A4-04` | retry classification and durable retry scheduling |
| `A4-05` | health policy, watchdog coordinator and service adapters |
| `A4-06` | append-only timeline and evidence metadata integration |
| `A4-07` | verified timeline cursors, paging and caller-driven replay |
| `A4-08` | durable consumer offsets and explicit at-least-once batches |
| `A4-09` | process-local single-flight protection for consumer batches |

## Retired aliases

Early draft PRs used ModelRig task numbers `T-030` through `T-034` for the five
Agent 4 scopes. Those numbers already belong to unrelated Agent 3/ROADMAP work
and are retired as Agent 4 identities.

Historical PR numbers and Git branch refs remain useful provenance, but they do
not define the work identity. New branches, docs, reviews and follow-on slices
must use the `A4-*` IDs and `agent/a4-*` prefix.

## Activation boundary

The A4-06 timeline, A4-07 replay layer, A4-08 consumer offsets and A4-09
single-flight guard are explicit storage/read composition contracts, not runtime
activation. Constructing them starts no thread, timer, scheduler, network request
or Agent 3 work. The consumer flight guard is process-local and coordinates only
callers sharing the same instance. Any runtime mount, recurring ingestion loop,
distributed consumer lease, binary evidence vault or cross-process writer is a
separate integration decision.
