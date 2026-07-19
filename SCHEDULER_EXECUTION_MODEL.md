# Scheduler execution model — T-018 explicit single-flight

**Status: draft implementation and tests only. Not merged into the physical-validation candidate.**

ModelRig deliberately starts with one scheduler execution lane:

- `execution_model=single_flight`;
- `max_concurrency=1` and every other value is rejected;
- a competing tick receives `busy=true` and claims nothing;
- no in-memory queue exists;
- each occurrence is claimed from SQLite only after the previous one is terminal;
- the durable `due_at` order is the queue and provides natural backpressure;
- shutdown lets the active ToolGate call finish, then blocks the next claim;
- a claim/storage exception releases the lane for a later tick;
- status exposes the model, bound and count of busy ticks.

This is safer than a worker pool for the first Scheduler pilot. It preserves the
existing occurrence ledger, approval, revocation and recovery truth without
introducing cross-thread cancellation or result-ordering ambiguity. A future pool
would require a separate reviewed design and migration; increasing an environment
number cannot enable it.

Revocation is stronger under this model than under the former batch claim: if
occurrence A pauses schedule B, B is never reserved as the next item. It spends no
budget, creates no in-flight occurrence and remains durably paused in SQLite.

## Acceptance evidence in the draft

`tests/worker_scheduler_single_flight.py` proves:

1. unsupported concurrency values are rejected;
2. a slow tool leaves only one reserved occurrence;
3. the remaining backlog stays due in SQLite;
4. a concurrent tick returns busy and reserves nothing;
5. a stop callback drains the active tool but takes no next claim;
6. a later flight processes the backlog in due order;
7. each schedule consumes one budget slot;
8. a claim exception releases the lane.

`tests/worker_schedule_revoke.py` proves that a preceding tool can pause the next
schedule before any claim or budget reservation. `tests/worker_schedule_service.py`
additionally proves that service status publishes the explicit model and bound.
Physical pilot evidence is still required before Scheduler promotion.
