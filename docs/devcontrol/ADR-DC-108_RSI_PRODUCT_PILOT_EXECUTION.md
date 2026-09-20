# ADR-DC-108 — Execute the first product-pilot Tier-A task exactly once

## Decision

ADR-DC-108 is the first product-pilot boundary allowed to launch a process.

It consumes one live ADR-DC-107 execution plan and delegates the only process
launch to the existing `run_single_verified_tier_a_command_with_receipt` path.
No alternate executor is introduced.

Immediately before launch, the Tier-A receipt orchestrator captures its own
pre-execution Git snapshot and proves that its SHA-256 exactly matches the
ADR-DC-106 snapshot bound into ADR-DC-107. A different staged patch therefore
cannot be substituted after planning.

## Crash-safe one-shot consumption

Execution authority is keyed by the signed `execution_nonce_sha256`.

Before any executor call, ADR-DC-108 writes a create-once lock to a canonical
host-admin-controlled ledger:

- Windows: `C:\Program Files\ModelRig\DevControl\state\rsi-pilot-exact-task-product-pilot-execution-ledger-v1`
- POSIX test/reference host: `/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-product-pilot-execution-ledger-v1`

The lock binds the exact ADR-DC-107 plan, ADR-DC-106 snapshot, ADR-DC-105
capability, ADR-DC-104 admission, DevelopmentTask and fixed command.

A lock, pending receipt or final receipt for the nonce makes another launch
inadmissible. This remains true across process restart. A crash or launch error
after reservation is therefore **spent/needs recovery**, never silently
retryable.

After the Tier-A command returns a canonical receipt, ADR-DC-108 durably writes
and reads back the product-pilot execution receipt. Live authentication requires
the exact final receipt and lock bytes to remain present.

## Receipt

The durable receipt contains the complete canonical Tier-A command receipt plus
bindings back through ADR-DC-107/106/105/104. It also records:

- ledger identity and nonce consumption key;
- prepare/start/complete timestamps;
- durable replay-guard and receipt-publication evidence;
- command pass/fail;
- workspace preservation/reset; and
- whether recovery is required.

A serialized copy is evidence only. It does not regain live execution or
verification authority without the process-local binding to the authenticated
upstream capability and exact durable ledger files.

## Authority after execution

ADR-DC-108 never grants local commit, remote write, push, PR mutation, merge,
release, deploy or production activation authority. The execution nonce remains
non-reusable.

A completed receipt still requires ADR-DC-109 verification. A consumed launch
that fails before a canonical receipt requires a dedicated recovery path and
cannot be retried with the same nonce.
