# DC-L06 preflight — Tier-A authority identities and materialization

**Status:** implementation slice · exact-head validation and independent review pending  
**Pull request:** #386  
**Branch:** `agent/devcontrol-dc-l06-tier-a-authority`  
**Branch base:** `main @ 3ede93313233e65599f2fb29b4c64e58f7432990`  
**Locked source:** PR #338 @ `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Prerequisites:** DC-L03, DC-L04 and DC-L05 landed

## Purpose

DC-L06 is the first landing slice where immutable catalog authority, signed
physical Windows evidence and the native containment substrate meet. It lands
the identities needed to convert an exact signed report into a leased command
registry and a deterministic retained v1 launch plan.

The slice does **not** launch a process. It does not stage a runtime closure,
capture execution results, inspect Git, issue command receipts, perform
independent semantic review, publish anything remotely or activate DevControl.

## Exact authority boundary

This slice owns:

- the canonical execution-lease schema and immutable lease model;
- one shared `TierAExecutionError` identity and canonical hash helpers;
- the reviewed application environment allowlist and fail-closed validator;
- canonical directory, workspace-root and regular-file authority;
- physical-evidence capture during catalog materialization;
- leased command registry identity and task rebinding protection;
- the retained v2 stage-local toolhost hash;
- the retained v1 launch-plan schema, model and deterministic builder;
- an import-only `_tier_a_execution_core.py` over already-landed identities; and
- a dormant `tier_a_authority.py` surface exposing only this slice.

## Deliberate source projection

Four focused private modules, two schemas and one extraction test are copied
exactly from the locked source head. The final source branch cannot otherwise be
copied byte-for-byte because it imports later-slice authority or refers to a
protocol identity removed by the already-landed hardened catalog.

Four progressive production files are therefore projected:

1. `_tier_a_execution_core.py` omits the DC-L08 legacy runner.
2. `_tier_a_legacy_toolhost.py` replaces future closure/execution files with the
   exact DC-L06 stage-local bundle while preserving the v2 hash domain.
3. `_tier_a_materialization.py` binds to the landed
   `LocalExecutableHashVerifier` rather than the removed generic protocol.
4. `tier_a_authority.py` exposes only lease, environment, path,
   materialization, toolhost and v1 plan identities.

Seven source tests are projected away from the future package facade, v2/v3
plans, execution result, runtime closure and executor. Their replacement
assertions explicitly prove those later surfaces remain absent. The repository
workflow-coverage contract is also progressively extended so CI proves that all
twenty DevControl test modules landed through DC-L06 are discovered.

## Hard exclusions

DC-L06 must not contain or expose:

- `_run_tier_a_launch_plan` or `run_verified_tier_a_command`;
- `tier_a_execution.py`, `tier_a_execution_v3.py` or `tier_a_result.py`;
- runtime staging or runtime-closure authority;
- trusted Git, command receipt, semantic review or publisher authority;
- credentials, network writes, remote Git or GitHub mutation;
- package-level activation or product-to-DevControl imports; or
- merge, release, deployment or production activation authority.

## Fail-closed invariants

- Unknown lease or plan fields reject.
- Signed evidence must bind the exact task, base, catalog, toolchain, rig,
  workspace, toolhost and deny-network boundary.
- A lease cannot be rebound to another task.
- Unreviewed environment keys or values reject.
- Relative, missing, symlinked or changed authority paths reject.
- Toolhost and workspace bytes changed after evidence issuance reject.
- A failed physical probe cannot issue a lease.
- The two literal stage-local bundle projections must be identical.
- Any later-slice module in the DC-L06 bundle is a scope failure.

## Review and merge gate

The final pull-request head must differ from the recorded base by exactly the 27
paths in `exact-path-allowlist.json`. All applicable CI, CodeQL and diagnostics
workflows must pass on that exact head. An independent reviewer distinct from
the author must then approve that same head. Any subsequent commit makes the
validation and verdict stale.
