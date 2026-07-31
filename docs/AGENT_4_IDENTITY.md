# Agent 4 identity and ownership contract

**Owner:** Sol  
**Runtime status:** dormant and caller-driven  
**Authoritative branch prefix:** `agent/a4-*`

## Ownership

Sol owns:

- `worker/app/agent4/**`;
- Agent 4-specific tests and support cases;
- `agent4/**` and `docs/AGENT_4_*` contracts.

Host/backend/client integration outside those paths remains Claude-owned. Shared integration boundaries and `HANDOFF.md` require parity evidence and coordination.

## Stable work identities

| ID | Scope |
|---|---|
| `A4-01` | foundation, lifecycle and startup recovery |
| `A4-02` | durable checkpoints |
| `A4-03` | resource leases and caller-driven admission |
| `A4-04` | retry classification and durable failure handling |
| `A4-05` | health policy, intervention coordinator and service adapters |
| `A4-06` | reserved for append-only timeline/evidence integration |

## Retired aliases

Early draft PRs used ModelRig task numbers `T-030` through `T-034` for the five Agent 4 scopes. Those numbers already belong to unrelated Agent 3/ROADMAP work and are retired as Agent 4 identities.

Historical PR numbers and Git branch refs remain useful provenance, but they do not define the work identity. New branches, docs, reviews and follow-on slices must use the `A4-*` IDs and `agent/a4-*` prefix.

## Activation boundary

This identity migration does not activate Agent 4. Importing the package starts no thread, timer, host cadence, network request or Agent 3 work. Any future runtime mount or recurring host loop is a separate integration decision and must be tested against the existing dormant contracts.
