# DC-L09 preflight — trusted Git runtime, command receipt and final facade

**Status:** implementation and exact-head validation in progress  
**Branch:** `agent/devcontrol-dc-l09-trusted-git-receipt-facade`  
**Base:** `main @ 70a40a27201ccaa33b1dffe0fff65faa113cd0f7`  
**Locked source:** PR #338 @ `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Depends on:** merged DC-L08

## Purpose

DC-L09 lands one complete, pinned local Git runtime, joins its immutable identity
to a verified Tier-A command receipt and exposes the sole final public execution
facade. The default catalog remains empty and normal package import remains
dormant.

## Exact source boundary

Seventeen source paths are copied byte-for-byte from the locked source head:
three documents, four schemas, seven Python modules and three tests. The source
implements complete runtime capture, crash-durable staging and recovery,
no-shell bounded local Git execution, canonical workspace snapshots, mutation
reset and the final `tier_a_execution.py` facade.

## Progressive projections

Seven landed surfaces are advanced from DC-L08:

- `.github/workflows/_tests.yml` activates all 31 portable modules plus bounded
  Windows subprocess and Git-aware receipt contracts;
- `devcontrol/README.md` records the DC-L09 authority and exclusions;
- `_tier_a_legacy_toolhost.py` and `tier_a_authority.py` advance the signed
  authority domain to v7 and bind all trusted-Git, receipt and facade modules;
- H10R and Slice 9 tests recognize the final facade while keeping package root,
  compatibility core and authority surfaces non-executing; and
- `tests/workflow_test_coverage.py` requires the complete L09 test and Windows
  contract inventory.

## Hard exclusions

- no remote Git transport, fetch or push;
- no credential helper, prompt, token, key or inherited Git configuration;
- no GitHub mutation, reviewer request, ready conversion or merge adapter;
- no semantic-review, publisher, release, deployment or activation authority;
- no product import of `kaliv_dev_control`; and
- no non-empty default command catalog.

## Merge gates

- exact 32-path diff and zero commits behind `main`;
- all seventeen source blobs match PR #338 exactly;
- v7 bundle identity is identical in toolhost and authority modules;
- package root, compatibility core, runtime staging and authority expose no
  process-launch functions;
- final facade routes only to v3 execution and the sole receipt orchestrator;
- trusted Git remains local-only, bounded, no-shell and credential-free;
- portable tests, native Windows receipt execution, CodeQL and diagnostics pass
  on one frozen head;
- zero unresolved review threads; and
- independent exact-head approval before terminal merge authority is exercised.
