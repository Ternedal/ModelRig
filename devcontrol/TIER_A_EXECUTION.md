# Tier-A execution bridge

Slice 9 connects the signed physical-isolation evidence contract to the dormant
Windows AppContainer launcher. It does **not** activate autonomous development,
registered tools, Agent 3, Agent 4, releases, merges or production deployment.

Slice 10A adds deterministic trusted-runtime staging as a separate preparation
primitive. It deliberately does not change the public execution path yet.

## Authority chain

A command can reach the Windows launch boundary only through this chain:

1. an immutable `kaliv-development-task/v1` grants one reviewed command ID;
2. the command exists in an immutable `ModelRigCommandCatalog`;
3. the operator-controlled `Toolchain` binds its tool ID to one absolute binary
   and SHA-256;
4. `WindowsPhysicalIsolationVerifier` reloads exactly one canonical signed
   physical report named by the task's isolation attestation;
5. the report signature, freshness, task SHA, base SHA, catalog SHA, toolchain
   SHA, boundary, network mode and all eleven physical probes are verified;
6. verification issues a `kaliv-development-execution-lease/v1` artifact;
7. the lease is converted into a
   `kaliv-development-tier-a-launch-plan/v1` artifact bound to the canonical
   workspace path, staged executable hash and complete Tier-A authority bundle;
8. the public runtime API repeats steps 4–7 immediately before launch;
9. Windows creates the command in a zero-capability AppContainer, suspended,
   assigns its Job Object limits and only then resumes it.

A persisted launch plan is audit evidence. It is not independently executable
authority. The low-level plan executor is private and is not exported by the
package.

## Code identity

The physical report's `toolhost_sha256` covers all source files that can issue,
transform or execute Tier-A authority:

- Windows Job Object, AppContainer and Tier-A environment modules;
- package initialization code;
- task, catalog, command, workspace and signed-evidence validation;
- the lease, plan and verified runtime bridge itself.

Changing any one of these files invalidates the physical report and prevents a
new lease or launch plan from being issued.

`runtime_staging.py` is intentionally not in this bundle yet because Slice 10A
cannot issue or execute a launch plan and is not imported by the package
initialization path. The integration slice must add it to the bundle and require
fresh physical evidence in the same change.

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

`TrustedRuntimeStager` can prepare one executable from a separate absolute
operator-controlled runtime root. It verifies the exact leased task, command,
catalog, toolchain and signed workspace root before copying anything.

The source executable must be regular, non-empty, link-free, physically inside
the operator root and match its toolchain SHA-256. It is copied to the
deterministic path:

```text
.kaliv/runtime/<tool-id>/<executable-sha256>/<source-basename>
```

The copy is hashed while written, flushed, fsynced and published with an atomic
no-overwrite hard link. Existing matching bytes are reusable; existing different
bytes fail closed and are never replaced.

The canonical `kaliv-development-runtime-staging-receipt/v1` artifact binds the
task, command, catalog, toolchain, execution lease, signed workspace authority,
hashed source-path identity, executable bytes and deterministic destination.
Reload verification rehashes both the operator source and the staged copy.

This receipt is not executable authority. See `RUNTIME_STAGING.md` for the full
boundary and non-goals.

## Current limitations

The bridge remains deliberately dormant.

- No registered ModelRig tool calls `run_verified_tier_a_command`.
- The hosted Windows proof uses a synthetic signed report to test the complete
  software wiring. It is not the physical I0b result required for activation.
- Trusted standalone executable staging exists, but the public fresh-verification
  runtime path does not consume its receipt yet.
- Staging a single executable is not a complete Python or Go runtime closure;
  dependent DLLs, Python libraries and Go toolchain trees remain unprovisioned.
- Launch plans currently require workspace-root working directory. The existing
  backend Go commands use `backend/` and therefore remain unavailable through
  this bridge.
- Standard output and standard error capture are not yet part of the native
  AppContainer process wrapper, so Slice 9 proves exit status and boundary
  enforcement rather than a complete `CommandReceipt` execution path.
- No GitHub write, branch push, draft-PR creation, merge, release, settings or
  feature-switch authority is granted.

The next safe slice is to integrate the staging receipt into the single public
fresh-verification path, add `runtime_staging.py` to the signed authority bundle,
and add bounded stdout/stderr capture. That must be followed by a complete
physical eleven-probe campaign on the selected rig.
