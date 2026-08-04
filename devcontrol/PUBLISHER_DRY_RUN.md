# Authenticated publisher intent and dry-run receipt

Slice 10J adds a canonical, separately authenticated publisher-intent boundary over
one exact verified Slice 10I readiness artifact. It produces a deterministic
receipt describing the draft-only publication steps that a future separately
controlled publisher could perform. It does not perform any of those steps.

The module contains no Git transport, GitHub client, network write, repository
mutation, branch push, pull-request create/update, reviewer request,
ready-for-review, merge, release, settings, deployment or runtime-activation
adapter. Human merge authority remains unchanged.

## Honest human-invocation claim

The request records `human_invoked: true`, but that field alone is not treated as
proof. The request must also be authenticated with a publisher-only HMAC key bound
to an exact publisher actor. That publisher actor must differ from both:

- the developer actor that produced the Slice 10H request; and
- the independent semantic reviewer actor.

The signature proves possession of the trusted publisher key and exact artifact
binding. It cannot prove that a biological human personally pressed a button. A
production operating procedure must keep the publisher key behind a genuinely
human-controlled account, process or hardware boundary if that stronger claim is
required.

The publisher HMAC key is not a GitHub credential and grants no network authority.
Copying it into the developer or reviewer workspace destroys the intended actor
separation.

## Publisher request

`kaliv-development-publisher-request/v1` embeds the complete
`kaliv-development-authenticated-draft-pr-readiness-proposal/v1` and independently
binds:

- readiness artifact SHA-256;
- exact task SHA-256;
- repository, exact base SHA and deterministic base/head branches;
- exact staged-patch SHA-256 and byte count;
- deterministic title and body hashes;
- publisher actor and publisher system identities;
- one explicit 64-hex invocation nonce;
- the fixed publisher dry-run policy SHA-256;
- the exact ordered publication-intent operation set;
- `human_invoked: true`;
- `dry_run_only: true`;
- `draft_only: true`;
- `merge_authority: human`.

Construction immediately re-verifies the complete Slice 10I artifact using the
existing `SemanticReviewVerifier`. A stale Tier-A authority hash, changed task,
changed patch, changed reviewer signature or changed deterministic proposal cannot
enter a publisher request.

The request builder accepts no repository, base SHA, branch, title, body, patch,
operation list, command, argument vector, workspace, GitHub client, token or
credential parameter. Publication presentation and candidate identity are inherited
only from the verified readiness artifact.

## Publisher signature

`kaliv-development-signed-publisher-request/v1` wraps the canonical request with:

- publisher key ID;
- `hmac-sha256` algorithm identity;
- domain-separated signature over the key ID and exact canonical request bytes.

The trusted publisher keyring binds each key ID to one publisher actor. Verification
fails on an unknown key, actor mismatch, changed request, invalid signature,
another task, readiness drift, policy drift or current execution-authority drift.

No signing secret, verification secret or GitHub credential is serialized into any
artifact.

## Fixed dry-run operation plan

A verified signed request produces exactly five ordered
`PublisherDryRunOperation` objects:

1. `verify_exact_readiness`
   - re-identifies the readiness, task, execution authority, semantic request and
     signed semantic verdict;
   - requires no repository or network write.
2. `materialize_exact_candidate_commit`
   - describes applying the exact staged patch to the exact base and creating one
     commit with deterministic message and publisher actor;
   - marks a repository write as required, but no network write.
3. `create_proposed_branch`
   - describes creating the deterministic Slice 10I head branch from the planned
     candidate commit;
   - marks a repository write as required, but no network write.
4. `push_proposed_branch`
   - describes publishing only that deterministic branch to the bound repository;
   - marks both repository and network writes as required.
5. `create_draft_pull_request`
   - describes creating a draft PR with the exact base/head, title and body hash;
   - fixes `draft=true` and `merge_authority=human`;
   - marks both repository and network writes as required.

Each operation is canonical, ordered, hashable and marked
`planned_not_executed`. Later operations bind the SHA-256 of the preceding relevant
plan, preventing silent reordering or substitution.

The plan deliberately contains no operation for:

- requesting reviewers;
- marking ready for review;
- merging;
- releasing;
- changing repository settings;
- deploying;
- activating ModelRig or unattended self-development.

## Dry-run receipt

`kaliv-development-publisher-dry-run-receipt/v1` embeds the complete signed
publisher request and the exact deterministic operation plan. It is structurally
valid only when all execution and result claims remain false:

- `executed`;
- `repository_write_performed`;
- `network_write_performed`;
- `commit_created`;
- `branch_created`;
- `branch_pushed`;
- `pull_request_created`;
- `ready_for_review`;
- `reviewers_requested`;
- `merged`;
- `released`;
- `deployed`.

`dry_run` must remain true and `merge_authority` must remain `human`. Changing any
operation parameter, ordering, identity, signature or result flag makes canonical
reload fail closed.

`PublisherDryRunGate` returns true only after re-verifying:

- exact task identity;
- complete Slice 10I readiness;
- trusted semantic-review signature;
- current Tier-A v6 execution authority;
- trusted publisher key and publisher actor;
- exact publisher request;
- fixed publisher policy;
- deterministic five-operation plan;
- zero performed writes or publication results.

A true gate result means only that the dry-run evidence is valid. It is not a
publication authorization token and cannot be submitted to GitHub by this module.

## Canonical offline files

Create-once helpers are provided for:

- publisher requests;
- signed publisher requests;
- publisher dry-run receipts.

They require absolute regular link-free input paths, safe existing parent
directories, bounded UTF-8 JSON, exact canonical bytes and non-existing output
paths. Writes use a temporary file, `fsync` and atomic replacement. Trailing
newlines, reordered representation, links and overwrite attempts fail closed.

## Relationship to Tier-A and GitHub

Slice 10J consumes evidence only. It is intentionally outside the Tier-A v6
execution bundle and cannot issue leases, stage runtimes, execute commands, inspect
or reset a Git workspace, or create a Tier-A receipt. Therefore it does not require
a new physical I0b campaign.

The operation plan names future publication effects, but names are data rather than
callable adapters. No Git or GitHub library is imported. No host, authorization
header, token, credential, HTTP request or subprocess-based Git command exists in
the module.

## Adversarial proof

Portable tests prove:

- canonical request, signed request and dry-run receipt round-trip;
- exact readiness, task, patch, title/body, publisher, nonce, signature and policy
  binding;
- developer/reviewer/publisher actor separation;
- publisher key-to-actor binding;
- invalid, wrong-secret and unknown-key signatures fail closed;
- another task or current execution-authority drift fails closed;
- fixed deterministic five-step operation order and chaining;
- changed operation parameters or requested-operation sets fail closed;
- every performed/result flag fails when changed to true;
- merge authority cannot leave `human`;
- schema field parity;
- canonical files are create-once and noncanonical bytes are rejected;
- builder APIs expose no caller-selected publication identity or live write surface;
- the module contains no live GitHub/network adapter.

## Deliberate limits

Slice 10J does not provide:

- proof that the publisher key was used by a biological human;
- publisher-key provisioning, rotation, expiry, revocation or hardware custody;
- replay prevention beyond an explicit invocation nonce and operational key policy;
- creation of a candidate commit or branch;
- a Git remote, GitHub credential or network write;
- branch push or PR creation/update;
- reviewer requests or ready-for-review conversion;
- merge, release, settings, deployment or runtime activation.

A later slice may define a separately controlled live publisher that consumes one
fresh verified request and performs only the fixed draft-only operations. Such a
slice must introduce explicit replay/freshness handling, least-privilege credential
custody, remote identity verification and post-write receipts before any real
network mutation is considered.
