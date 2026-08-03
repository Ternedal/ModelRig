# Tier-A execution bridge

Slice 9 connects signed physical-isolation evidence to the dormant Windows
AppContainer launcher. Slice 10A adds deterministic trusted-runtime staging, and
Slice 10B makes that staging mandatory in the only public execution path.

None of these slices activates autonomous development, registered tools, Agent 3,
Agent 4, GitHub writes, releases, merges or production deployment.

## Authority chain

A command can reach the Windows launch boundary only through this chain:

1. an immutable `kaliv-development-task/v1` grants one reviewed command ID;
2. the command exists in an immutable `ModelRigCommandCatalog`;
3. the operator-controlled `Toolchain` binds its tool ID to one absolute source
   executable and SHA-256;
4. `WindowsPhysicalIsolationVerifier` reloads exactly one canonical signed
   physical report named by the task's isolation attestation;
5. the report signature, freshness, task SHA, base SHA, catalog SHA, toolchain
   SHA, boundary, network mode and all eleven physical probes are verified;
6. verification issues a `kaliv-development-execution-lease/v1` artifact;
7. `TrustedRuntimeStager` verifies the exact lease and source executable, copies
   it to the signed workspace and emits a
   `kaliv-development-runtime-staging-receipt/v1`;
8. that receipt is revalidated and exactly one leased command template is rebound
   to the verified staged executable, without mutating the original registry;
9. a `kaliv-development-tier-a-launch-plan/v1` is built from that staged registry
   and binds the canonical workspace, executable SHA and complete authority bundle;
10. the private executor rehashes workspace authority, code identity and executable
    immediately before launch;
11. Windows creates the command suspended in a zero-capability AppContainer,
    assigns its Job Object limits and only then resumes it.

A persisted launch plan is audit evidence, not independently executable authority.
The low-level plan executor remains private and is not exported by the package.
The public `run_verified_tier_a_command` function now requires an explicit,
separate `trusted_runtime_root`; callers cannot supply a pre-staged executable as
a substitute for the receipt flow.

## Code identity

The physical report's `toolhost_sha256` covers every source file that can issue,
transform or execute Tier-A authority:

- Windows Job Object, AppContainer and Tier-A environment modules;
- package initialization code;
- task, catalog, command, workspace and signed-evidence validation;
- trusted-runtime staging and receipt rebinding;
- the lease, plan and verified runtime bridge itself.

`runtime_staging.py` is now inside this signed bundle. The Slice 10B change
therefore invalidates every older physical report. A new lease or launch requires
a fresh exact-bundle report and attestation.

## Environment boundary

The Windows initialization environment is derived from a fixed positive list.
The command may additionally receive only these exact reviewed values:

- `CI=1`;
- `MODELRIG_DEVCONTROL=1`;
- `GOTOOLCHAIN=local`;
- `PYTHONDONTWRITEBYTECODE=1`.

Unknown keys, altered values, case-insensitive duplicates and collisions with
Windows initialization fields fail closed. Parent credentials such as GitHub
tokens, model keys, cookies, authorization headers and signing keys are not
inherited.

## Trusted runtime staging

The source executable must be regular, non-empty, link-free, physically inside a
separate operator-controlled root and match the toolchain SHA-256. It is copied to:

```text
.kaliv/runtime/<tool-id>/<executable-sha256>/<source-basename>
```

The copy is hashed while written, flushed, fsynced and published with an atomic
no-overwrite hard link. Existing matching bytes are reusable. Existing different
bytes fail closed and are never replaced.

The receipt binds task, command, catalog, toolchain, execution lease, signed
workspace authority, hashed source-path identity, executable bytes and destination.
Before launch, `bind_for_launch` rehashes both the operator source and workspace
copy, then creates a new one-command `LeasedCommandRegistry` whose only difference
is `argv[0]`. Arguments, cwd, timeout, environment, lease, catalog, toolchain and
attestation are preserved exactly.

The stager still has no process-launch method and is not exported through the
package top level.

## Current limitations

The bridge remains deliberately dormant.

- No registered ModelRig tool calls `run_verified_tier_a_command`.
- The hosted Windows proof uses a synthetic signed report to test software wiring;
  it is not the physical I0b result required for activation.
- Staging one executable is not a complete Python or Go runtime closure; dependent
  DLLs, Python libraries and Go toolchain trees remain unprovisioned.
- Launch plans currently require workspace-root working directory. Existing
  backend commands use `backend/` and remain unavailable through this bridge.
- Standard output and error capture are not yet part of the native AppContainer
  wrapper, so execution returns an exit code rather than a complete
  `CommandReceipt`.
- No GitHub write, branch push, draft-PR creation, merge, release, settings or
  feature-switch authority is granted.

The next safe slice is bounded native stdout/stderr capture with strict byte
budgets and deterministic hashes, without creating a second public execution
surface. It must then be followed by the complete physical eleven-probe campaign
on the selected rig.
