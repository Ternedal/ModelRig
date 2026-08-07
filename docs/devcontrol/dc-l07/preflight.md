# DC-L07 preflight — deterministic runtime staging, closure, plan and result evidence

**Status:** implementation slice in progress  
**Branch:** `agent/devcontrol-dc-l07-runtime-evidence`  
**Base:** `main @ 0d64603fdb28c7b59a91007f527606314779f5f3`  
**Locked source:** PR #338 @ `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Depends on:** merged DC-L06

## Purpose

DC-L07 lands deterministic runtime staging, signed runtime-closure identity,
Tier-A launch plans v2/v3 and bounded execution-result evidence. It prepares
and verifies runtime authority but exposes no supported process-launch entrypoint.

## Locked source families

- `streaming_publication.py`;
- `runtime_staging.py`;
- `_runtime_closure_common.py` and `runtime_closure_*.py`;
- `tier_a_plan.py` and `tier_a_result.py`;
- `backend/cmd/modelrig-version-check/**`;
- runtime, closure, plan and result schemas;
- Slice 10A–10F and publication-concurrency tests; and
- only the progressive Tier-A surfaces required to bind the stage-local bundle.

## Required finding closure

Streaming publication must make prepared permission metadata crash durable,
including the Windows permission-repair path, before positive publication
evidence can be issued.

## Hard exclusions

- no legacy or modern Tier-A executor;
- no process launch;
- no trusted Git runtime, trusted-Git staging schema or command receipt;
- no credentials, remote Git, GitHub mutation, publisher or activation authority;
- no dependency on DC-L08 or later slices.

## Merge gates

- exact source-path disposition and provenance;
- exact final path and symbol allowlists;
- no future-slice imports;
- load-bearing red/green mutation coverage;
- full CI, CodeQL and diagnostics on the frozen exact head;
- zero unresolved review threads; and
- exact-head review before human terminal merge authority is exercised.
