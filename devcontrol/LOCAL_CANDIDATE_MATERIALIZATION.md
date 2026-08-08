# Local candidate materialization

Slice 10L consumes one verified Slice 10K preflight receipt and creates a
deterministic candidate commit and proposed branch in a new isolated local bare
repository. H2 migrates every Git operation to the shared complete trusted Git
runtime and upgrades the canonical materialization receipt to v2.

The result remains an offline local artifact. This boundary has no configured
remote, credential, network write, push, pull-request mutation, reviewer request,
ready-for-review conversion, merge, release, settings, deployment or activation
authority.

## Required authority chain

Materialization re-verifies:

1. the passing Tier-A command receipt;
2. authenticated semantic approval;
3. draft-only readiness;
4. authenticated publisher intent;
5. the one-time publisher authorization lease;
6. consumed replay evidence and the preflight receipt;
7. task, actors, policy identities and lease time; and
8. the current Tier-A execution authority identity.

Materialization time cannot precede preflight or reach the lease expiry boundary.

## Complete trusted Git runtime

The public API requires a `TrustedGitRuntime`, not an executable path and hash.
The runtime transaction binds:

- the exact Git executable;
- the exact `GIT_EXEC_PATH` helper directory;
- positive-listed PATH directories;
- runtime libraries;
- every file's SHA-256, size, role and executable flag; and
- one deterministic manifest SHA-256.

`TrustedGitRunner` supplies the staged absolute executable, exact helper path,
exact runtime PATH/library paths and isolated Git configuration. The runtime and
isolation locations are reverified before and after every Git command.

The Linux real-Git proof stages Git, the actual `git-upload-pack` helper used by
local `file://` fetch and the executable/helper dynamic libraries. The native
Windows receipt proof separately stages a fresh Git-for-Windows package.

## Source repository boundary

The source must be an absolute link-free standalone worktree with a real `.git`
directory or a standalone bare repository. The verifier rejects:

- linked worktrees and `.git` file indirection;
- `commondir`;
- object alternates;
- shallow history;
- replacement objects;
- non-SHA-1 object format;
- missing exact authorized base objects; and
- linked critical Git storage.

Source evidence binds normalized path identity, repository kind, refs, HEAD,
symbolic HEAD, worktree status where applicable, raw base commit/tree object
hashes and complete state identity. The source is reread after materialization
and must remain identical.

## Create-once transaction

The materialization root must already exist and be absolute and link-free. The
transaction ID is deterministic from the preflight identity. The final directory
is create-once and contains exactly:

- `repository.git`;
- `receipt.json`;
- `isolated-home`;
- `isolated-xdg`;
- `disabled-hooks`;
- `empty-template`;
- `empty-global-config`; and
- `isolated-temp`.

Isolation directories must remain empty and exact. The candidate index is removed
before publication. The canonical receipt is written inside a temporary sibling
transaction, the complete layout is verified and the directory is then renamed
to its final path.

H2 does not claim directory-entry fsync or crash recovery. Ambiguous power-loss
recovery remains a separate hardening requirement.

## Deterministic object creation

The fixed operation sequence is:

1. initialize a new bare SHA-1 repository with the empty staged template;
2. fetch only the exact authorized parent through local `file` protocol;
3. read the parent tree into an isolated index;
4. apply the exact authenticated binary patch to the index;
5. write the candidate tree;
6. reproduce and compare the exact patch bytes from parent to candidate tree;
7. verify the raw tree payload and object ID;
8. create deterministic publisher-bound author and committer metadata;
9. create one exact-parent commit with the Slice 10J commit message;
10. reconstruct and compare the raw commit payload;
11. create exactly one proposed branch with create-only `update-ref`; and
12. set symbolic HEAD to that branch.

The source repository is never configured as a remote and must remain unchanged.

## Receipt v2

`kaliv-development-local-candidate-materialization-receipt/v2` retains all v1
source and candidate evidence and upgrades nested Git evidence to
`kaliv-development-local-git-evidence/v2`.

The Git evidence contains:

- executable SHA-256, byte count, basename and version;
- complete `TrustedGitRuntimeEvidence` including manifest SHA-256, full file count
  and bytes, helper path, runtime PATH and library directories; and
- SHA-1 object-format binding.

The receipt also binds all upstream artifact hashes, invocation nonce,
materialization policy, time, transaction identity, source state, raw tree and
commit objects, exact patch reproduction, branch ref and symbolic HEAD.

Every remote/write/result flag is fixed false and merge authority is fixed human.

## Verification

`verify_local_candidate_materialization` and
`LocalCandidateMaterializationGate.valid`:

- reverify the complete upstream authority chain;
- require exact canonical receipt bytes and transaction layout;
- reverify the supplied complete Git runtime;
- require runtime evidence to match the receipt exactly;
- re-inspect source state and raw base objects;
- inspect the bare repository's object format, refs, symbolic HEAD, parent, tree,
  raw commit, reproduced patch and absence of remotes; and
- fail on any extra file, ref, remote, source change or runtime change.

## Internal legacy helper core

The earlier executable-only 10L implementation is retained under an internal
module name solely so its pure source/object inspection and validation routines
can be reused without manually rewriting the already adversarially tested logic.
After import, its executable materialize/verify/gate entrypoints and
`TrustedLocalGit` symbol are removed from that module namespace.

This is not claimed as physical source removal. Further decomposition and removal
of the retained helper core remain maintainability work.

## Deliberate limits

This boundary does not provide streaming output capture, crash-durable publication
or recovery receipts, distributed replay consensus, protection against a separate
administrator/kernel component, asymmetric production signing, remote validation,
Git remote configuration, network writes, push, pull-request mutation, reviewer
requests, ready conversion, merge, release, settings, deployment or unattended
activation.
