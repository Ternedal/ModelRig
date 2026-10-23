# Continuum approval integration decision (ADR-001)

Status: proposed, not production enabled.

The scoped ApprovalStore introduced in this prototype is NOT wired into
continuum_state.transition() or task_store.move(). Those older prototype
functions still accept an arbitrary nonempty approval_token. Therefore they
MUST NOT be used to authorize side-effecting operations.

## Required integration
1. Resolve authenticated actor identity from the existing ModelRig auth layer.
2. Evaluate the canonical kaliv-capability/v2 descriptor and existing policy.
3. At approval time, issue a scoped grant for exact task, actor, capability,
   task revision and expiry. User confirmation must occur through trusted UI.
4. At execution time, validate and consume the grant in the same durable
   transaction as the authorized command reservation; otherwise a crash between
   consumption and task update could strand work.
5. Queue an idempotent command with a unique operation ID and explicit budget.
6. Worker verifies authorization and records a redacted execution receipt.
7. Revoke unused grants on cancellation, task revision change or logout.

Do not treat a grant as a substitute for capability policy. Do not persist raw
grant tokens in logs, events or client-visible task status. Protect the SQLite
file with filesystem permissions and private storage.

## Known limitations of current isolated prototype
- Grants are not yet linked to a trusted human approval action.
- No revocation endpoint, actor ownership model or key rotation.
- The standalone store cannot provide atomicity with a separate task DB.
- No deployment, client integration or live authorization tests.
- Tests are source-committed but have not been run by this session.

Promotion gate: first eliminate arbitrary-token approval in transition(),
then introduce transactional command reservation and integration tests. Keep
all write-capable pathways disabled until that gate passes.
