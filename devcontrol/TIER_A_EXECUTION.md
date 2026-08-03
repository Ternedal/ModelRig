# Tier-A execution bridge

Slice 9 connects signed physical-isolation evidence to the dormant Windows
AppContainer launcher. Slice 10A adds deterministic trusted-runtime staging,
Slice 10B makes that staging mandatory in the only public execution path, and
Slice 10C adds bounded native stdout/stderr evidence.

None of these slices activates autonomous development, registered tools, Agent 3,
Agent 4, GitHub writes, releases, merges or production deployment.

## Authority chain

A command can reach the Windows launch boundary only through this chain:

1. an immutable `kaliv-development-task/v1` grants one reviewed command ID and
   fixed runtime/output budgets;
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
9. a `kaliv-development-tier-a-launch-plan/v2` is built from that staged registry
   and binds workspace, executable, timeout, output budget and authority bundle;
10. the private executor rehashes workspace authority, code identity and executable
    immediately before launch;
11. Windows creates the command suspended in a zero-capability AppContainer with
    an exact three-handle inheritance list;
12. the configured Job Object is assigned before the child is resumed;
13. stdout and stderr are concurrently drained to EOF, fully hashed and only
    bounded prefixes are retained;
14. execution emits a canonical
    `kaliv-development-tier-a-execution-result/v1` artifact.

A persisted launch plan is audit evidence, not independently executable authority.
The low-level plan executor remains private and is not exported by the package.
The public `run_verified_tier_a_command` function requires an explicit, separate
`trusted_runtime_root`; callers cannot supply a pre-staged executable as a
substitute for the receipt flow.

## Code identity

The physical report's `toolhost_sha256` v3 covers every source file that can
issue, transform, launch or report Tier-A authority:

- Windows Job Object, AppContainer, environment and output-capture modules;
- package initialization code;
- task, catalog, command, workspace and signed-evidence validation;
- trusted-runtime staging and receipt rebinding;
- the private byte-identical lease/materialization core;
- launch-plan v2, result validation and the single public runtime bridge.

Adding `windows_capture.py`, `tier_a_result.py` and the v2 bridge invalidates every
older physical report. A new lease or launch requires a fresh exact-bundle report
and attestation.

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

The stager has no process-launch method and is not exported through the package
top level.

## Native output boundary

The capture layer cannot create a process or select command authority. It wraps
the existing AppContainer `CreateProcessW` call only to add:

- an inherited read-only `NUL` handle for stdin;
- one inherited stdout pipe write handle;
- one inherited stderr pipe write handle;
- `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` containing exactly those three handles.

`bInheritHandles=TRUE` is accepted only together with that exact handle list.
Unrelated inheritable handles in the parent therefore cannot enter the child.
Parent-side pipe write handles are closed immediately after `CreateProcessW`, so
EOF depends only on the isolated Job Object process tree.

Two non-daemon reader threads drain stdout and stderr concurrently. Every byte is
included in its stream's SHA-256 and total byte count. Memory retention is split
deterministically across the signed task budget:

```text
stdout prefix = ceil(max_output_bytes / 2)
stderr prefix = floor(max_output_bytes / 2)
```

The result stores binary prefixes as canonical base64. It also records full stream
hashes, full byte counts, retained byte counts and explicit truncation flags.
A truncated stream therefore remains identifiable without retaining unbounded
output.

## Timeout behavior

The fixed launch timeout is the smaller of the task budget and catalog template.
On timeout, the complete Job Object is terminated and closed before capture waits
for EOF. The process is reaped, both stream hashes are finalized and a canonical
result with `timed_out=true` and `passed=false` is produced.

The public runtime then raises `TierAExecutionTimeout` carrying that result. A
caller cannot mistake timeout evidence for a successful command, while the audit
chain still retains output emitted before termination.

## Current limitations

The bridge remains deliberately dormant.

- No registered ModelRig tool calls `run_verified_tier_a_command`.
- The hosted Windows proof uses synthetic signed evidence to test software wiring;
  it is not the physical I0b result required for activation.
- Staging one executable is not a complete Python or Go runtime closure; dependent
  DLLs, Python libraries and Go toolchain trees remain unprovisioned.
- Launch plans currently require workspace-root working directory. Existing
  backend commands use `backend/` and remain unavailable through this bridge.
- `TierAExecutionResult` does not yet claim a complete development
  `CommandReceipt`: workspace-before/after Git identities and reset evidence remain
  owned by the separate command executor.
- No GitHub write, branch push, draft-PR creation, merge, release, settings or
  feature-switch authority is granted.

The next safe slice is a signed runtime-closure manifest plus bounded
workspace-relative working-directory support, beginning with one independently
reviewed self-contained command. It must not weaken staging, output capture or the
fresh physical-evidence requirement.
