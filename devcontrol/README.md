# Kaliv Development Control Plane

This directory contains the dormant, fail-closed foundation for controlled
self-development in ModelRig. It is deliberately **not** connected to ordinary
ModelRig tool registration, Agent 3, Agent 4, GitHub publication, merge, release or
production activation.

The implementation currently reaches **Slice 10L**. One exact task can pass through
reviewed command authority, fresh signed physical Windows evidence, native Tier-A
containment, deterministic runtime closure, Git-aware execution evidence,
independent semantic approval, authenticated draft-PR readiness, signed publisher
intent, a time-bounded one-time authorization and finally local-only creation of
the exact candidate commit and proposed branch inside a new isolated bare Git
repository.

The chain still contains no GitHub credential, network-write adapter, branch push,
pull-request write, reviewer request, ready-for-review, merge, release, settings or
deployment authority.

## Implemented authority layers

### Slices 1–4 — task, workspace, campaign and structural review

- immutable `kaliv-development-task/v1` contracts with exact base SHA, path policy
  and resource budgets;
- detached exact-SHA workspaces, scoped reads/search and bounded unified patches;
- fixed command templates and canonical command receipts;
- hash-chained campaign state with terminal failure modes;
- independent structural review request/verdict contracts;
- deterministic draft-PR proposal data only;
- durable controlled storage, exclusive locks and stale-writer rejection; and
- human-only merge authority.

### Slice 5 — catalog and read-only GitHub boundary

- immutable command catalog and independently hash-bound toolchain;
- trusted tool IDs instead of caller-supplied executables;
- exact task, base, catalog and toolchain binding;
- project-command network mode fixed to `deny`;
- fixed-host GET-only GitHub reads with redirects disabled; and
- no branch, push, PR, merge, release or settings operation.

### Slice 6 — signed physical Windows evidence

- eleven mandatory I0b probes covering identity, workspace access/escape,
  networking, cleanup, reboot, memory/process limits and compatibility;
- failed probes remain representable but cannot authorize execution;
- separate collector and approver identities;
- canonical HMAC-SHA256 signed evidence;
- exact task, catalog, toolchain, rig, workspace and authority-code binding; and
- exactly one fresh matching report required.

### Slices 7–9 — native containment and verified-only execution

- child created suspended and assigned to a kill-on-close Job Object before resume;
- process-memory and active-process limits enforced by Windows;
- deterministic zero-capability AppContainer with approved-workspace access only;
- no network capability and a positive-list environment;
- valid signed physical evidence issues an immutable execution lease;
- the low-level executor is private; and
- the only public runtime path re-verifies signed evidence, workspace, executable
  and authority code immediately before launch.

### Slices 10A–10B — deterministic runtime staging

- separate absolute operator-controlled runtime root;
- regular, non-empty, link-free and hash-bound source executable;
- deterministic no-overwrite staging under:

  ```text
  .kaliv/runtime/<tool-id>/<executable-sha256>/<source-basename>
  ```

- canonical staging receipt binding task, lease, catalog, toolchain, source,
  destination and bytes;
- fresh receipt required for every public launch; and
- no caller-selected pre-staged executable or second execution surface.

### Slice 10C — bounded native output evidence

- exact task output bound included in launch authority;
- only `NUL` stdin, stdout and stderr inherited through an explicit handle list;
- stdout and stderr drained concurrently to EOF;
- every byte included in complete stream hashes and byte counts;
- deterministic bounded prefixes retained as canonical base64; and
- timeout kills the complete Job Object and returns non-passing evidence.

### Slice 10D — signed runtime closure and exact cwd

- command-specific signed exact-file closure manifest;
- exact task, command, catalog, toolchain, lease, workspace, source-root,
  entrypoint, cwd and file-set binding;
- deterministic multi-file staging under:

  ```text
  .kaliv/runtime-closures/<tool-id>/<manifest-sha256>/...
  ```

- traversal, device names, alternate streams, case collisions, links, junctions,
  hardlinks, missing and extra files rejected;
- complete staged tree rehashed after staging and immediately before launch; and
- workspace-relative cwd revalidated inside `CreateProcessW`.

### Slice 10E — reviewed standalone version-check closure

- self-contained Go implementation at `backend/cmd/modelrig-version-check`;
- isolated one-command catalog using tool ID `modelrig-version-check`;
- default catalog unchanged;
- unsigned single-file closure proposal only; and
- extra runtime files/directories and the legacy Python profile fail closed.

See `VERSION_CHECK_CLOSURE.md`.

### Slice 10F — runtime lifetime immutability

- staged closure reverified after workspace ACL provisioning;
- protected read/execute-only DACL for the operator and exact AppContainer SID;
- open handles deny write/delete-sharing for the complete Job Object lifetime;
- overwrite, replacement, rename, deletion and insertion denied while active;
- original DACLs restored only after confirmed process-tree completion; and
- ambiguous cleanup retains protection rather than reopening a mutation window.

This boundary does not claim resistance against a separate administrator or kernel
component.

### Slice 10G — Git-aware Tier-A command receipt

- exactly one task-authorized command and identical required test;
- exact base `HEAD`, staged patch, unstaged diff and untracked-path identity;
- only the existing verified Tier-A runtime path is invoked;
- optional staged input accepted only with zero unstaged or untracked input;
- before/after/reset snapshots are canonical and hash-bound;
- workspace mutation creates a non-passing receipt and exact-base reset evidence;
- timeout preserves complete non-passing Tier-A and Git evidence; and
- Tier-A authority bundle v6 includes the receipt orchestrator.

### Slice 10H — authenticated semantic-review evidence

- canonical request embeds the exact staged patch bytes, complete passing Slice 10G
  receipt, task criteria, fixed policy and current v6 authority hash;
- every acceptance criterion receives exactly one ordered assessment;
- approval requires every criterion satisfied and zero findings;
- developer and reviewer identities must differ;
- reviewer-only domain-separated HMAC binds request, patch, receipt, task, policy,
  authority, actor and key;
- canonical request/verdict files are bounded, link-free and create-once; and
- the module cannot execute commands, reset Git or write to GitHub.

A valid signature proves artifact and actor-key binding, not semantic competence.
A separately operated human or model reviewer must actually perform the review.

See `SEMANTIC_REVIEW.md`.

### Slice 10I — authenticated draft-PR readiness proposal

- embeds the complete task, exact Slice 10H request and signed approval verdict;
- re-verifies reviewer signature, exact task and current Tier-A v6 authority;
- uncertainty, findings or any non-approval cannot be represented as ready;
- repository, proposed head branch, title and body are deterministic;
- staged patch, receipt, reviewer, policies and authority remain independently
  hash-bound;
- fixed to `draft: true` and `merge_authority: human`; and
- no branch-push, PR-create/update, reviewer-request, ready, merge, release or
  deployment adapter.

See `DRAFT_PR_READINESS.md`.

### Slice 10J — authenticated publisher intent and dry-run evidence

- `kaliv-development-publisher-request/v1` embeds the complete verified Slice 10I
  readiness artifact;
- binds exact task, repository, base, deterministic branches, patch, title/body,
  publisher actor/system, invocation nonce, policy and ordered operation set;
- publisher actor must differ from developer and semantic reviewer;
- publisher-only domain-separated HMAC signature binds the exact request;
- the publisher signing key is not a GitHub credential;
- deterministic dry-run plan describes readiness verification, candidate-commit
  materialization, local branch creation, future branch push and future exact draft
  pull-request creation;
- every operation remains `planned_not_executed`;
- all repository/network/result flags remain false; and
- no Git library, GitHub client, remote host, token, HTTP request or subprocess Git
  command exists in the Slice 10J module.

A publisher signature proves key possession and exact intent binding. It does not
prove that a biological human personally initiated the request.

See `PUBLISHER_DRY_RUN.md`.

### Slice 10K — one-time publisher authorization and replay ledger

- `kaliv-development-publisher-authorization-lease/v1` embeds and re-verifies the
  complete signed Slice 10J request;
- a fourth authorization-issuer actor must differ from developer, semantic
  reviewer and publisher;
- issuer-only domain-separated HMAC binds the complete lease;
- exact GitHub repository name and immutable numeric repository ID are bound as
  trusted configuration;
- a fixed least-privilege policy permits only exact proposed-branch contents write
  and creation of the exact draft pull request;
- merge, ready-for-review, reviewer requests, releases, settings, workflows,
  secrets, tags, deployments and other capabilities are explicitly denied;
- artifacts contain no credential or token material and permit no reusable
  credential;
- canonical issue and expiry timestamps limit a lease to 1–900 seconds;
- every lease is fixed to one use, draft only and human-only merge authority;
- `PublisherReplayLedger` consumes the exact invocation nonce using atomic
  `O_CREAT | O_EXCL` create-once storage;
- sequential and concurrent replay cannot both succeed;
- preflight evidence requires a currently valid lease and matching consumed nonce;
- postcondition evidence can represent only `execution_state: not_executed`; and
- every observation/write/commit/branch/push/PR/review/merge/release/deployment
  result remains false.

The remote numeric ID is trusted configuration rather than a network lookup. The
issuer key, repository identity and replay-ledger directory are external trusted
operating boundaries.

See `PUBLISHER_AUTHORIZATION.md`.

### Slice 10L — local candidate commit and proposed branch

- `kaliv-development-local-candidate-materialization-receipt/v1` embeds the complete
  verified Slice 10K preflight receipt;
- authorization is reverified at the explicit materialization timestamp;
- `TrustedLocalGit` requires one absolute regular link-free Git executable whose
  complete bytes match an operator-supplied SHA-256;
- Git is rehashed before and after every fixed command;
- HOME, XDG/global config, hooks and templates are isolated and empty;
- terminal prompting, credential-manager interaction, replacement objects,
  automatic maintenance and signing are disabled;
- all Git protocols are denied except local `file://` import;
- the source must be a standalone non-shallow SHA-1 worktree or bare repository
  containing the exact authorized base commit;
- linked worktrees, `commondir`, object alternates and linked object storage fail
  closed;
- refs, HEAD/status and raw base commit/tree objects are SHA-256-bound before and
  after materialization, proving the source remained unchanged;
- one new bare SHA-1 repository is created in a fresh transaction directory;
- only the exact base is imported, with no tags, remote configuration, tracking
  refs or submodule recursion;
- the exact authenticated binary patch is applied to an isolated temporary index;
- parent-to-tree diff bytes must reproduce the authenticated patch exactly;
- raw tree and commit objects are independently SHA-256- and Git-SHA-bound;
- author, committer, message and timestamp are deterministic from the exact
  publisher request and authorization lease;
- the only created ref is the exact deterministic proposed local branch;
- symbolic HEAD points to that branch and no remote may exist;
- the isolated transaction is published create-once with an exact layout and
  canonical `receipt.json`; and
- later verification rechecks the complete authority chain, trusted Git bytes,
  source state, transaction layout, sole ref, no-remote boundary, raw objects and
  exact patch reproduction.

Slice 10L creates real Git objects locally but does not publish them. The trusted
Git executable, source repository and materialization root remain external
operating boundaries. The module does not claim protection against a separate
administrator or kernel component.

See `LOCAL_CANDIDATE_MATERIALIZATION.md`.

## Reviewed command authority

The default registry remains empty. Naming a command ID in a task does not make it
executable. The command must also exist in an immutable catalog, have an exact
operator binding, pass fresh signed physical evidence and complete the signed
runtime-closure chain.

The default ModelRig catalog contains:

- `modelrig.version.check`;
- `modelrig.devcontrol.tests`;
- `modelrig.workflow.test-coverage`;
- `modelrig.backend.vet`; and
- `modelrig.backend.tests`.

Slice 10E uses a separate isolated catalog rather than silently changing this
list. Slice 10G requires a one-command task. Slices 10H–10K consume completed
evidence only. Slice 10L may create the exact authorized commit and branch only in
its isolated local bare repository; it cannot add command authority, launch Tier-A
execution, provision credentials or publish anything remotely.

## Physical evidence operator flow

The physical harness writes one canonical unsigned report matching
`schemas/windows-isolation-physical-report-v1.schema.json`. Signing is a separate
operator action and its key must remain outside the developer workspace.

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control sign-physical-report \
  C:/ModelRigEvidence/i0b-unsigned.json \
  C:/ModelRigEvidence/i0b-signed.json \
  --key-file C:/ModelRigOperator/isolation.key \
  --key-id operator-key-2026
```

Independent verification uses:

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control verify-physical-report \
  C:/ModelRigEvidence/attestation.json \
  --evidence-root C:/ModelRigEvidence \
  --key-file C:/ModelRigOperator/isolation.key \
  --key-id operator-key-2026
```

HMAC is appropriate only while each key is protected by its required separate
operator/process boundary. A physical-evidence, semantic-review, publisher or
authorization key copied into the developer workspace invalidates the claimed
independence.

## Explicit remaining boundaries

The control plane still cannot:

- run arbitrary shell commands or model-selected executable arguments;
- execute without exact fresh signed physical evidence;
- manufacture a genuine physical I0b result without the eleven probes;
- automatically discover a transitive PE/DLL, Python or Go runtime closure;
- perform semantic analysis without a separately operated reviewer;
- prove that publisher or authorization keys were used by biological humans;
- provision, store, rotate, revoke or use production reviewer, publisher,
  authorization or GitHub credential material;
- discover, clone or network-validate the configured remote repository;
- provide distributed replay consensus across uncoordinated hosts;
- protect trusted key, ledger, Git executable, source-repository or materialization
  boundaries against a separate administrator or kernel component;
- configure a Git remote or perform a network write;
- push the locally materialized branch;
- create or update a pull request;
- request reviewers or mark a pull request ready for review;
- merge, release, change settings or deploy; or
- activate unattended self-development.

No registered ModelRig tool calls the Tier-A bridge, receipt orchestrator,
semantic-review boundary, readiness builder, publisher dry-run boundary,
publisher-authorization boundary or local-candidate materializer. Hosted CI uses
synthetic and local Git evidence to prove software contracts and does not replace
the selected rig's physical campaign, independent semantic review or production
key/tool custody.

## Run tests

```bash
cd devcontrol
python -m unittest discover -s tests -v
```

The portable suite proves the Slice 10H–10L artifact, signature, actor-separation,
tamper rejection, deterministic proposal/plan/commit, time-window,
least-privilege, atomic replay, exact local Git object and no-remote/no-write
contracts. The native Windows gate separately proves Job Object, AppContainer,
environment, signed physical evidence, exact runtime closure, lifetime
immutability, strict handle inheritance, bounded output, timeout cleanup and the
real Git-aware Tier-A receipt.

## Validate a task

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control validate-task examples/task.json
```

The package remains dependency-free so authority and evidence primitives can be
reviewed without bootstrapping an agent execution environment.
