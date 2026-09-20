# ADR-DC-109 — Verify recovery and close the first product-pilot execution

## Decision

ADR-DC-109 closes the first product-pilot task only after a fresh Trusted-Git
snapshot proves that the repository is in the exact state recorded by ADR-DC-108
and its canonical Tier-A command receipt.

The boundary consumes a **live** ADR-DC-108 receipt so the retained ADR-DC-105
Tier-A substrate can be revalidated. It then performs read-only Git evidence
capture.

ADR-DC-109 never invokes the product command and never resets, cleans, stages or
commits Git.

## Successful execution

For a passing ADR-DC-108 receipt:

- the Tier-A receipt must say the workspace was unchanged;
- no reset may have been performed;
- the expected post-execution snapshot must equal the exact ADR-DC-106
  pre-execution snapshot; and
- the freshly captured current snapshot must equal that exact hash.

Only then can the first product-pilot task be marked closed.

## Failed execution and recovery verification

A failed ADR-DC-108 receipt always requires recovery verification.

If the Tier-A orchestrator observed mutation and performed its built-in
exact-base reset, ADR-DC-109 requires:

- canonical reset evidence;
- base HEAD;
- zero staged, unstaged and untracked recovery state; and
- a fresh current snapshot identical to the reset snapshot.

If the command failed without changing the workspace, the unchanged Tier-A
post-state itself is the expected safe recovery state.

ADR-DC-109 does not perform a second recovery action. Unexpected drift after
ADR-DC-108 fails closed rather than deleting potentially unrelated user changes.

## Closure authority

A valid verification receipt sets:

- `tier_a_execution_verified=true`;
- `post_execution_workspace_verified=true`;
- `product_pilot_execution_closed=true`;
- `first_product_pilot_task_closed=true`; and
- `next_boundary_stack_consolidation_required=true`.

No commit, remote write, push, PR mutation, merge, release, deploy or production
authority is granted. The execution nonce remains non-reusable.
