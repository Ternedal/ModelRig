# Slice 10E — reviewed standalone version-check closure

Slice 10E adds one concrete, self-contained runtime-closure candidate without
activating it or weakening the existing fail-closed authority chain.

## What is included

- `backend/cmd/modelrig-version-check` is a small Go command that performs the
  existing read-only version-drift check against `VERSION` and the four lockstep
  version sites.
- `modelrig_version_check_closure_catalog()` returns an isolated catalog with
  exactly one command profile:

  ```text
  command_id = modelrig.version.check
  tool_id    = modelrig-version-check
  args       = []
  cwd        = .
  network    = deny
  ```

- `ModelRigVersionCheckClosureBuilder` can emit an unsigned
  `kaliv-development-runtime-closure-manifest/v1` only for that exact profile.
- The trusted runtime root must contain exactly one regular, non-empty,
  single-link entrypoint plus only the parent directories needed to contain it.
- The entrypoint bytes must match the exact operator `ToolBinding` SHA-256.
- The task, catalog, toolchain, lease, signed workspace and trusted-runtime-root
  identities are copied into the manifest and rechecked by the existing closure
  verifier.

## Deliberate separation from the default catalog

The existing `modelrig_command_catalog()` remains unchanged and continues to use
its prior Python-backed `modelrig.version.check` profile. Slice 10E does not
silently replace that authority.

Selecting the standalone profile therefore changes the catalog SHA-256 and
requires all of the following to be issued again for the exact task:

1. an operator toolchain binding to the built executable and its SHA-256;
2. a fresh physical Windows-isolation report bound to the isolated catalog and
   toolchain;
3. a fresh execution lease;
4. an independently signed runtime-closure manifest.

A report or closure from the existing default catalog cannot authorize the
standalone profile.

## Build candidate

From `backend/` on the operator-controlled build system:

```powershell
go test ./cmd/modelrig-version-check
go build -trimpath -o C:\ModelRigRuntime\version-check\bin\modelrig-version-check.exe ./cmd/modelrig-version-check
```

The runtime directory supplied to the closure builder must contain no other file
or unrelated directory. Build caches, source trees, symbols and logs stay outside
that root.

## Authority boundary

The builder emits an **unsigned proposal only**. It cannot:

- sign or approve its own manifest;
- manufacture physical isolation evidence;
- stage or execute the binary;
- register a ModelRig tool;
- activate Agent 3, Agent 4 or autonomous development;
- write to GitHub, push, create or merge a pull request;
- release or deploy anything.

The existing runtime-closure verifier, deterministic stager, launch-plan binding,
AppContainer, Job Object, output capture and timeout cleanup remain the only path
to execution.

## Validation

Portable tests prove that the builder:

- produces a canonical one-file manifest that can pass the existing independent
  signer, verifier and stager chain;
- rejects every other command ID;
- rejects the legacy Python-backed profile;
- rejects extra files or directories in the trusted runtime root;
- rejects a workspace not named by the execution lease.

The Go package tests prove success, drift detection, invalid semver handling and
argument rejection. No tool is registered and no production switch changes.
