# Product-pilot execution session

This facade is the canonical in-process path for running the first exact-task
product-pilot execution after a completed product-pilot start.

It adds **no new authority**. It only composes the reviewed boundaries in this
order:

1. ADR-DC-104 — execution admission
2. ADR-DC-105 — production Tier-A executor capability
3. ADR-DC-106 — exact Trusted-Git workspace snapshot
4. ADR-DC-107 — execution plan bound to that exact snapshot
5. ADR-DC-108 — durable, crash-safe one-shot Tier-A execution
6. ADR-DC-109 — fresh post-execution verification/recovery closure

The public call is:

`run_pilot_exact_task_product_pilot_execution_session(start_state)`

where `start_state` is the live completed ADR-DC-102 start receipt or the live
ADR-DC-103 `completed_verified` recovery receipt already accepted by ADR-DC-104.

The facade performs no Git operations, process launch, ledger write, network
operation or repository mutation itself. Those remain owned by their canonical
boundaries.

If ADR-DC-108 fails after its durable execution lock has been written, the
facade stops immediately. It does **not** retry ADR-DC-108 and does not call
ADR-DC-109. The execution nonce may already be spent and must be handled through
recovery/manual intervention.

A successful call returns the live authenticated ADR-DC-109 verification receipt
with the first product-pilot task closed. Commit, remote write, push, PR mutation,
merge, release, deploy and production activation authority all remain false.
