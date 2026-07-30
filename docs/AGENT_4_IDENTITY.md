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
| `A4-07` | cross-process timeline writer lock and process-safe facade |

## Retired aliases

Early draft PRs used ModelRig task numbers `T-030` through `T-034` for the five
Agent 4 scopes. Those numbers already belong to unrelated Agent 3/ROADMAP work
and are retired as Agent 4 identities.

Historical PR numbers and Git branch refs remain useful provenance, but they do
not define the work identity. New branches, docs, reviews and follow-on slices
must use the `A4-*` IDs and `agent/a4-*` prefix.

## Activation boundary

The A4-06 timeline and A4-07 writer lock are storage and composition contracts,
not runtime activation. Constructing them starts no thread, timer, scheduler,
network request or Agent 3 work, and creates no directory until an explicit
operation. Any runtime mount, recurring ingestion loop, binary evidence vault or
distributed fencing system is a separate integration decision.
