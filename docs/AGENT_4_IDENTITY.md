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
| `A4-03` | resource leases and caller-driven admission |
| `A4-04` | retry classification and durable failure handling |
| `A4-05` | health policy, intervention coordinator and service adapters |
| `A4-06` | append-only campaign timeline, immutable evidence references and durable delivery |
| `A4-07` | verified, bounded timeline query cursors and stable snapshot paging |
| `A4-08` | bounded durable consumer batches over the A4-06 delivery cursor |
| `A4-09` | explicit dormant single-process composition of the B-reference architecture |
| `A4-10` | bounded transport-independent operator reads over the composed B runtime |
| `A4-11` | authoritative campaign state, durable audit-projection intents and caller-driven reconciliation |

## Retired aliases

Early draft PRs used ModelRig task numbers `T-030` through `T-034` for the five
Agent 4 scopes. Those numbers already belong to unrelated Agent 3/ROADMAP work
and are retired as Agent 4 identities.

Historical PR numbers and Git branch refs remain useful provenance, but they do
not define the work identity. New branches, docs, reviews and follow-on slices
must use the `A4-*` IDs and `agent/a4-*` prefix.

## Activation boundary

The Agent 4 package remains dormant. Importing it starts no thread, timer, host
cadence, network request or Agent 3 work. A4-06 adds explicit filesystem and
caller-driven delivery operations; A4-07 adds read-only query composition;
A4-08 adds only a bounded caller-driven batch wrapper; A4-09 wires these with the
lifecycle services but performs no recovery, dispatch or intervention itself;
A4-10 adds only bounded read composition over the same object graph; A4-11 stores
audit-projection intents with authoritative campaign state and reconciles them
only when a caller invokes a state-writing service or `reconcile_projections()`.
None subscribes to the event bus, mounts a runtime or activates recurring work.
Any future host integration or recurring loop is a separate integration decision
and must be tested against the existing dormant contracts.
