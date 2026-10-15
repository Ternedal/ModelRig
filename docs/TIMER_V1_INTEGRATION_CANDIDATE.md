# Timer V1 integration candidate (NOT a release)

This branch consolidates the stacked timer backend drafts (through #2189) into
one review target. It is intentionally distinct from the frozen Voice V1 #2164.

## What is implemented
- Parse bounded Danish timer intents and respond fail-closed.
- Inert UI handoff and canonical schedule preview (not authorization).
- Durable SQLite pending proposals, expiry and cancellation.
- Transactional proposal/ledger creation and state reconciliation.
- Revision-guarded transitions, capacity and retention rules.

## What is NOT implemented
- Authenticated, human-approved one-shot activation.
- Trusted alarm transport, client notification or acknowledgement.
- Recovery and delivery semantics for a running timer across restarts.
- A passing exact-head release qualification on this branch.
- Hardware/voice/client end-to-end testing.

## Release gates (all mandatory)
1. Resolve the stacked PR CI failures and pass exact-head on this branch.
2. Replace caller-supplied approval booleans with verified approval evidence.
3. Implement an atomic one-shot activation transaction (not recurring cadence).
4. Provide a registered delivery transport, with failure and retry semantics.
5. Verify cancellation races, restart behaviour and no false success.
6. Verify the client notification and audible alarm, including offline behaviour.
7. Review security and merge only after explicit release decision.

Until those gates pass, no claim that Kaliv can start a real timer is permitted.
Do not merge this candidate into protected main or alter worker 8099.
