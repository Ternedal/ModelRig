# ADR-DC-112 — Freshly verify a recovered execution after restart

## Decision

ADR-DC-112 is the fresh host-verification boundary for the one ADR-DC-111
resolution class `completed_ready_for_post_restart_verification`.

It does **not** restore ADR-DC-108 process-local execution authority and it
never launches the reviewed command again.

Instead it independently re-establishes current host authority and proves that
the durable completed execution still closes safely after a process restart.

## Durable execution evidence

ADR-DC-112 re-reads the permanent ADR-DC-108 execution lock and exact final
receipt from the canonical execution ledger. The state is observed again and
must still match the live ADR-DC-111 resolution.

A pending receipt appearing, lock drift, final-receipt drift or any identity
mismatch fails closed.

## Fresh host authority

The boundary resolves the canonical host-admin-controlled Tier-A executor
profile for the exact DevelopmentTask hash using the existing ADR-DC-036/105
production resolver.

It then requires:

- the host isolation attestation to match the durable task/base identity;
- the same signed physical report hash used by the Tier-A execution;
- reconstruction of the same Tier-A execution lease;
- the current canonical workspace path authority to equal that signed lease;
- the current control-plane toolhost hash to equal that signed lease;
- the current Trusted-Git runtime evidence to equal execution-time evidence;
- a fresh read-only Git snapshot to equal Tier-A's exact recorded post-state.

This prevents a different workspace, Git runtime, physical report, lease or
control-plane tree from being accepted merely because it has the same commit.

## Execution outcome

For a passing execution, the current workspace must still equal the exact
pre-execution snapshot and no reset may have occurred.

For a failed execution, ADR-DC-112 requires the same safe recovery semantics as
ADR-DC-109: either an exact-base reset was recorded and remains current, or the
failed command left the workspace unchanged.

In both cases the execution nonce remains spent.

## Authority

A successful ADR-DC-112 receipt closes the recovered execution and first pilot
task after restart, but grants no new execution or publication authority.

`retry_authorized`, `task_execution_authorized`, commit, remote write, push, PR
mutation, merge, release, deploy, production activation and nonce reuse all
remain false.

Only the live receipt returned by the current verification call has
`verification_authenticated` provenance. Reloaded JSON is audit evidence only.
That live provenance is revalidated against both the durable ledger and fresh
host/Git/workspace evidence whenever it is used.

## Next boundary

After successful post-restart verification, the next activity is stack/landing
consolidation. It is not another execution-authority boundary.
