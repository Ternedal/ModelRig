# Trusted Git runtime hardening (H2A)

## Status

H2A introduces a dormant, local-only boundary for capturing, staging, verifying and invoking one complete Git runtime package. It does not yet migrate `WorkspaceManager`, Tier-A Git workspace receipts or Slice 10L local candidate materialization. That migration is deliberately reserved for H2B after this package boundary has passed the full repository test matrix.

H2A adds no Git remote, credential, network transport, push, pull-request mutation, reviewer request, ready-for-review conversion, merge, release, settings or deployment authority.

## Problem addressed

The previous code used three inconsistent Git trust models:

1. `WorkspaceManager` checked `shutil.which("git")` but then executed the string `git` through inherited `PATH`.
2. Tier-A command receipts executed the string `git` through inherited `PATH`.
3. Slice 10L pinned and rehashed one absolute Git executable, but still inherited host `PATH` and did not bind the helper and runtime-library closure used by that executable.

Hashing one executable is not sufficient when Git can dispatch helpers from `GIT_EXEC_PATH` or load supporting libraries from directories outside the hashed boundary.

## H2A contracts

### Manifest

`TrustedGitRuntimeManifest` binds:

- exactly one executable relative path;
- one explicit Git helper directory (`GIT_EXEC_PATH`);
- an ordered positive-list of runtime `PATH` directories;
- every regular file below the reviewed runtime root;
- each file's exact relative path, SHA-256, size, executable flag and role;
- a deterministic domain-separated manifest SHA-256; and
- a bounded total file count and byte size.

Manifest capture is not an automatic trust decision. It produces reviewable content that an operator or build pipeline must pin explicitly before staging.

### Create-once staging

`stage_trusted_git_runtime`:

- accepts only absolute, existing, link-free source and staging roots;
- rejects symlinks, junctions and hard-linked files;
- rereads and rehashes every source file against the pinned manifest;
- copies every file into a temporary sibling transaction;
- applies deterministic executable/non-executable modes;
- verifies the complete staged tree before publication;
- writes a canonical staging receipt;
- publishes one deterministic transaction directory by rename;
- never overwrites an existing transaction; and
- uses an exclusive reservation file so simultaneous publishers produce at most one winner.

Directory-entry durability and crash recovery are intentionally not claimed by H2A. They remain part of the separate durability hardening track.

### Runtime verification

`TrustedGitRuntime` reopens the canonical receipt and verifies:

- the exact transaction identifier;
- the exact two-entry top-level layout (`runtime`, `receipt.json`);
- no extra or missing files;
- no links, junctions or hardlinks;
- every file's SHA-256 and byte count;
- executable-mode expectations; and
- canonical JSON bytes.

Verification runs before and after every command through `TrustedGitRunner`.

### Runner environment

`TrustedGitRunner` uses:

- the staged absolute executable path;
- exact staged runtime directories for child `PATH`;
- exact staged helper directory for `GIT_EXEC_PATH`;
- exact staged library directories for `LD_LIBRARY_PATH` and `DYLD_LIBRARY_PATH` where relevant;
- staged runtime directories in `PATH` for Windows DLL lookup;
- empty isolated HOME, XDG, hooks, template, temporary and global-config locations;
- `GIT_CONFIG_NOSYSTEM=1`;
- prompting and credential-manager interaction disabled;
- replacement objects disabled;
- signing disabled;
- automatic maintenance disabled;
- all protocols denied except local `file`; and
- a narrow allowlist for deterministic index, author and committer variables.

Host `PATH`, host Git helper directories and caller-selected environment fields are not forwarded.

H2A retains the existing post-process output-size check. Streaming output enforcement is a separate open hardening item and is not claimed here.

## Evidence

`TrustedGitRuntimeEvidence` records:

- manifest SHA-256;
- complete file count and bytes;
- exact executable SHA-256;
- observed Git version;
- helper path;
- runtime PATH directories; and
- runtime library directories.

## Adversarial proof

Portable tests demonstrate:

- deterministic manifests across different source roots;
- execution through the staged absolute executable;
- helper execution through the staged `GIT_EXEC_PATH`;
- complete replacement of an untrusted inherited `PATH`;
- exact staged library path;
- source mutation after capture fails closed;
- staged-file mutation fails closed;
- unexpected staged files fail closed;
- noncanonical receipts fail closed;
- simultaneous publication yields exactly one winner;
- repeat publication fails closed;
- symlinks and hardlinks fail closed;
- caller-selected `PATH` injection fails closed; and
- schema/property parity for manifest, receipt and evidence.

## H2B migration requirements

H2B should make this runtime mandatory for all three existing Git consumers:

1. workspace creation, verification and removal;
2. Tier-A before/after/reset Git evidence; and
3. local candidate materialization.

H2B must remove `shutil.which("git")`, bare `git` argv entries and inherited host `PATH` from those production paths. Existing artifact schemas should only be revised where the complete runtime identity must be bound into downstream evidence.

The migration must remain local-only and dormant. It must not add a remote, credential, network write, push, pull-request mutation, reviewer request, ready conversion, merge, release, settings or deployment authority.
