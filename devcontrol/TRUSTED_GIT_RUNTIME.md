# Trusted Git runtime hardening (H2)

## Status

H2 replaces the three inconsistent Git-selection boundaries with one staged,
content-addressed and reverified local Git runtime. The migration covers:

1. detached workspace creation, verification and removal;
2. Tier-A command before/after/reset Git evidence; and
3. Slice 10L local candidate object and branch materialization.

The subsystem remains dormant and local-only. H2 adds no credential, configured
remote, network write, push, pull-request mutation, reviewer request,
ready-for-review conversion, merge, release, settings or deployment authority.

## Problem addressed

The earlier implementation used three different trust models:

- workspace management checked `shutil.which("git")`, then executed the string
  `git` through inherited host `PATH`;
- Tier-A command receipts also executed the string `git` through inherited host
  `PATH`; and
- local materialization pinned one absolute executable, but did not bind the Git
  helper directory or the runtime libraries available to the process.

Hashing one executable is not a complete runtime identity when Git can dispatch
helpers from `GIT_EXEC_PATH` or load supporting libraries from other directories.

## Runtime manifest

`TrustedGitRuntimeManifest` binds a reviewed package containing:

- exactly one Git executable relative path;
- one explicit helper directory for `GIT_EXEC_PATH`;
- an ordered positive-list of child `PATH` directories;
- every regular file in the package;
- exact relative path, SHA-256, byte count, executable flag and role for each
  file; and
- a domain-separated deterministic manifest SHA-256.

Roles distinguish the executable, Git helpers, runtime libraries and other data.
Manifest capture is not itself a trust decision. An operator or controlled build
process must review and pin the exact manifest supplied to staging.

Manifest ordering is based on canonical POSIX-style relative paths and is stable
across Windows and POSIX path ordering.

## Create-once staging

`stage_trusted_git_runtime` accepts only absolute existing link-free source and
staging roots. It:

- rejects symlinks, junctions and hard-linked runtime files;
- rereads and rehashes every source file against the pinned manifest;
- copies files into a temporary sibling transaction;
- applies deterministic executable/non-executable modes;
- verifies the complete staged tree before publication;
- writes one canonical staging receipt;
- publishes one deterministic transaction directory; and
- refuses overwrite or concurrent duplicate publication.

The staging receipt binds the complete manifest, transaction identity and source
root path identity. A reopened transaction must contain exactly `runtime/` and
`receipt.json` at its top level.

Directory-entry durability and crash recovery are not claimed by H2. They remain
part of the separate durability hardening track.

## Shared trusted runner

`TrustedGitRunner` invokes only the staged absolute executable. Its child
environment contains:

- staged runtime directories only in `PATH`;
- the staged helper directory in `GIT_EXEC_PATH`;
- staged library directories in the applicable loader variables;
- isolated empty HOME, XDG, hooks, template, temporary and global-config
  locations;
- `GIT_CONFIG_NOSYSTEM=1`;
- disabled prompting and credential-manager interaction;
- disabled replacement objects, signing and automatic maintenance;
- all protocols denied except local `file`; and
- a narrow allowlist for deterministic index, author and committer variables.

Host `PATH`, host helper directories and caller-selected environment fields are
not forwarded. The complete staged transaction and isolation directories are
verified before and after every command.

The runner retains bounded in-memory stdout/stderr capture. The absolute ceiling
is 128 MiB because Slice 10L already authorizes binary patch evidence up to that
size; each operation still supplies a smaller concrete limit where possible.
Streaming capture and immediate process-tree termination on overflow remain open
hardening work.

## Migrated consumers

### Workspace manager

`WorkspaceManager` now requires a typed `TrustedGitRunner`. It no longer calls
`shutil.which("git")` and never inserts a bare `git` argv element. Worktree add,
HEAD verification, clean-status verification and worktree removal all use the
same runtime identity.

### Tier-A command receipt

The command-receipt orchestrator requires a typed `TrustedGitRunner`. Its
canonical receipt now embeds `TrustedGitRuntimeEvidence`, including manifest
SHA-256, complete file count and bytes, executable SHA-256, observed version,
helper path, runtime PATH and library directories.

Runtime evidence is captured before and after Tier-A execution. Identity drift
causes fail-closed reset handling and no passing receipt. The production receipt
module contains no direct subprocess Git invocation.

The native Windows proof stages a fresh Git-for-Windows runtime package and uses
that same runtime for repository setup, Git snapshots and receipt orchestration.

### Local candidate materialization

The public materialization API now requires a complete `TrustedGitRuntime`.
Receipt v2 retains executable evidence and additionally embeds the full runtime
evidence. Every source inspection, local fetch, isolated-index operation, object
creation, ref update and verifier read goes through the shared runner.

The previous executable-only implementation is retained as an internal helper
core for pure validation and object-inspection routines. Its executable public
entrypoints are removed from that module namespace after the facade imports the
required helpers. Physical removal and further module decomposition remain
maintenance work; H2 does not claim that the old source text no longer exists.

## Authority identity

The trusted-Git modules are reachable from workspace and Tier-A execution code,
so they are included in the Tier-A physical authority bundle. H1's recursive
import-closure test enforces that coverage.

The authority digest therefore changed. Earlier physical reports fail closed.
No replacement physical campaign is claimed; a fresh selected-rig I0b campaign
is required only after authority code is frozen for pilot use.

## Adversarial proof

Portable and native tests cover:

- deterministic manifests across source locations;
- exact staged executable and helper dispatch;
- replacement of inherited host `PATH`;
- exact helper and library path evidence;
- source mutation between capture and staging;
- staged runtime mutation and unexpected files;
- symlink, junction and hardlink rejection;
- create-once concurrent publication with one winner;
- canonical receipt reload;
- mandatory trusted runtime injection for every Git consumer;
- runtime identity drift during Tier-A receipt creation;
- real local `file://` base import using staged `git-upload-pack`;
- deterministic candidate tree, commit and receipt;
- remote/ref/transaction tampering; and
- retirement of the legacy executable-only write entrypoints.

## Deliberate limits

H2 does not provide:

- automatic trust approval of a discovered runtime;
- streaming output enforcement;
- crash-durable directory publication or recovery receipts;
- protection against a separate administrator or kernel component;
- asymmetric signing or hardware-backed key custody;
- a Git remote or network write;
- push, pull-request creation/update, reviewer request, ready conversion, merge,
  release, settings or deployment authority; or
- runtime activation or unattended self-development.
