# DC-L08 preflight — verified-only Tier-A execution

**Status:** implementation slice in progress  
**Branch:** `agent/devcontrol-dc-l08-verified-execution`  
**Base:** `main @ 3777dc456bf72238339e91f714dd239a97ec02b9`  
**Locked source:** PR #338 @ `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Depends on:** merged DC-L07

## Purpose

DC-L08 lands the private, verified-only Tier-A execution stage. Every process
launch must be bound to a fresh physical-evidence lease, a command-specific
signed runtime closure, deterministic staging, an exact v3 launch plan and the
existing Windows AppContainer plus Job Object substrate.

## Locked source paths

- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_runner.py`;
- `devcontrol/src/kaliv_dev_control/tier_a_execution_v3.py`; and
- `devcontrol/tests/test_h10r_tier_a_legacy_runner_extraction.py`.

The two executor modules remain source-exact. The extraction test is projected
to the DC-L08 boundary because the locked source test also asserts DC-L09's final
public facade and command-receipt integration.

## Progressive surfaces

- `.github/workflows/_tests.yml`;
- `devcontrol/README.md`;
- `_tier_a_execution_core.py`;
- `_tier_a_legacy_toolhost.py`;
- `tier_a_authority.py`;
- `test_slice9.py`; and
- `tests/workflow_test_coverage.py`.

## Hard exclusions

- no `tier_a_execution.py` final public facade;
- no `tier_a_command_receipt.py`;
- no trusted-Git runtime or staging schema;
- no remote Git, credentials, GitHub mutation, publisher or activation authority;
- no package-root, compatibility-core or authority-surface executor export.

## Merge gates

- exact 18-path diff and source provenance;
- exact executor symbol ownership;
- no DC-L09+ imports or files;
- package import remains dormant;
- closure-bound executor fails closed off Windows;
- real-Windows AppContainer, Job Object, bounded-output, timeout, cwd and runtime-lifetime tests;
- all repository, DevControl, CodeQL and diagnostics workflows on one frozen head;
- zero unresolved review threads; and
- independent exact-head approval before human terminal merge authority is exercised.
