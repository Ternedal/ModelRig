# Authenticated draft pull-request readiness

Slice 10I turns one exact Slice 10H semantic approval into a canonical,
self-contained draft pull-request readiness proposal. It remains an offline
evidence artifact. It does not push a branch, call GitHub, create or update a pull
request, request reviewers, merge, release, change settings, deploy or activate a
runtime tool.

## Required evidence

`AuthenticatedDraftPrReadinessProposal.from_evidence(...)` accepts only:

- one validated `kaliv-development-task/v1`;
- the exact `kaliv-development-semantic-review-request/v1` for that task;
- one `kaliv-development-signed-semantic-review-verdict/v1`;
- a configured `SemanticReviewVerifier` with reviewer-only trust material;
- the current control-plane root for execution-authority revalidation;
- an optional canonical base-branch name, defaulting to `main`.

The builder does not accept a repository, proposed head branch, title, body,
draft flag, merge authority, workspace, command ID, argument vector, catalog,
toolchain, Git transport or GitHub client.

The semantic verifier must successfully prove:

1. the task is the exact task embedded in the review request;
2. the request still matches the current Tier-A v6 execution authority;
3. the staged patch and complete passing Slice 10G receipt are unchanged;
4. the signed verdict is bound to the request;
5. the reviewer key is trusted and bound to the reviewer actor;
6. the signature is valid;
7. developer and reviewer actors remain separate;
8. the verdict decision is `approve`.

A request-changes or reject verdict cannot be represented as ready. Neither can an
approval containing findings, uncertain criteria or non-satisfied criteria.

## Canonical artifact

`kaliv-development-authenticated-draft-pr-readiness-proposal/v1` embeds:

- the complete canonical development task and task SHA-256;
- repository, exact base SHA and canonical base branch;
- a deterministic proposed head branch;
- deterministic title and body;
- exact staged-patch SHA-256 and byte count;
- exact Tier-A command-receipt SHA-256;
- the complete semantic-review request and its SHA-256;
- the complete signed semantic-review verdict and its SHA-256;
- reviewer actor and reviewer key identities;
- execution-authority, semantic-review-policy and proposal-policy identities;
- `draft: true`;
- `merge_authority: human`.

The proposed head branch is derived from the task ID, exact base SHA and staged
patch SHA. The title is derived from the task goal. The body is derived from the
task, evidence hashes, reviewer identity and proposed branches. A reloaded
artifact that changes any generated presentation field fails closed.

The artifact is intentionally self-contained. An auditor can recover the exact
task, patch bytes, Tier-A receipt, criterion assessments, findings, reviewer
identity and signature envelope from one canonical file. Signature verification
still requires the independently managed reviewer trust configuration.

## Fixed readiness policy

The proposal binds the domain-separated hash of a fixed policy requiring:

- one canonical task, request and authenticated approval;
- exact patch, receipt, reviewer, authority and policy binding;
- deterministic presentation fields;
- draft-only status and human merge authority;
- failure on mismatch, uncertainty, findings, signature failure, authority drift
  or noncanonical encoding.

Changing that policy changes `proposal_policy_sha256` and invalidates prior
readiness verification under the new policy.

## Canonical offline persistence

`write_authenticated_draft_pr_readiness_proposal(...)`:

- requires an absolute path;
- rejects links and junctions in the path;
- requires an existing regular parent directory;
- refuses overwrite;
- writes through a temporary file followed by atomic replacement;
- flushes and fsyncs before publication;
- returns the canonical artifact SHA-256.

`load_authenticated_draft_pr_readiness_proposal(...)` rejects:

- relative, linked or non-file paths;
- oversized files;
- invalid UTF-8 or JSON;
- unknown or missing fields;
- noncanonical JSON bytes;
- inconsistent nested task, request, receipt, verdict or presentation identities.

## Readiness gate

`DraftPrReadinessGate.ready(...)` returns true only when the canonical proposal can
be reverified against:

- the exact supplied task;
- the configured reviewer trust keyring;
- the current execution-authority code identity;
- the current fixed readiness policy.

It returns false on every typed mismatch. A true result means only that the exact
candidate has authenticated evidence suitable for a human-reviewed draft-PR
proposal. It is not permission to perform a Git or GitHub write.

## Relationship to earlier proposal evidence

Slices 1–4 retain `kaliv-development-draft-pr-proposal/v1` for the original
structural campaign flow. Slice 10I does not silently reinterpret or replace that
schema. It adds a separate stronger artifact for the Tier-A receipt plus
independent semantic-review chain.

A later integration may require both structural campaign evidence and this
authenticated readiness artifact. Slice 10I itself does not bridge either artifact
to a write adapter.

## Adversarial proof

Portable tests prove:

- complete canonical round-trip;
- deterministic branch, title and body generation;
- task, patch, receipt, request, signed-verdict, reviewer, authority and policy
  binding;
- rejection of changed hashes, title, body, head branch, draft flag or merge
  authority;
- rejection of another task, invalid signature, untrusted key, authority drift and
  non-approval;
- schema field parity;
- create-once canonical file exchange;
- absence of branch-push, PR-create/update, reviewer-request, merge, release or
  deployment adapters from the module API.

The existing native Windows Tier-A and Git-aware receipt gates are unchanged.
Slice 10I is outside the Tier-A v6 execution bundle and therefore does not require
a new physical I0b campaign.

## Deliberate limits

Slice 10I does not provide:

- a semantic model or reviewer service;
- reviewer-key provisioning, rotation, revocation or hardware-backed custody;
- branch creation, commit creation or push;
- pull-request creation, update, review request or ready-for-review transition;
- merge, release, settings or deployment authority;
- runtime registration or unattended self-development activation.

A future slice may add a separately controlled human-invoked publisher that
consumes this artifact. Such a publisher must reverify the artifact immediately
before use, remain draft-only, preserve human merge authority and keep all write
credentials outside the developer and reviewer environments.
