# Independent semantic review boundary

Slice 10H adds an offline, authenticated evidence boundary for semantic review of
one exact staged patch after one complete passing Slice 10G receipt. It does not
implement an AI model, call a model provider, execute project commands, inspect a
mutable workspace or write to GitHub. A separately operated reviewer consumes one
canonical request and returns one canonical signed verdict.

The control plane remains dormant and fail closed. Human merge authority is
unchanged.

## Trust boundary

The execution side may construct a `SemanticReviewRequest` only from:

- one validated `kaliv-development-task/v1`;
- the exact staged binary/full-index patch bytes;
- one complete passing `kaliv-development-tier-a-command-receipt/v1`;
- the current `tier_a_toolhost_sha256` v6 execution-authority identity;
- a named developer actor.

The request API deliberately accepts no workspace path, command ID, argument
vector, catalog, toolchain, executable, Git transport or GitHub client. The exact
command is inherited from the already completed receipt and one-command task.

The reviewer side receives only the serialized artifact. It has no callback into
Tier-A and no authority to alter the patch, reset the workspace, select another
command or launch a process.

## Canonical review request

`kaliv-development-semantic-review-request/v1` embeds:

- task ID, canonical task SHA-256, repository and exact base SHA;
- developer actor ID and task-derived command ID;
- execution-authority SHA-256 for the exact v6 code that produced the receipt;
- fixed semantic-review-policy SHA-256;
- the exact staged patch bytes as canonical base64;
- staged patch SHA-256 and byte count;
- the task acceptance criteria in their exact order;
- the complete nested Slice 10G receipt and its SHA-256.

The patch must be non-empty and at most 32 MiB. Its bytes and hash must match both
the before and after Git snapshots in the receipt. The receipt must prove:

- passing Tier-A execution;
- identical before and after workspace snapshots;
- no reset;
- no unstaged or untracked material;
- exact task, base and command binding.

A timeout, failed command, changed workspace or reset receipt cannot enter semantic
review as an approvable request.

## Fixed review policy

The request binds a domain-separated hash of the fixed v1 review policy. The
reviewer is instructed to:

1. use only the canonical request and not mutable workspace state or unstated
   external facts;
2. assess every acceptance criterion against the exact patch and complete receipt;
3. inspect material correctness, security, regression, maintainability and
   evidence risks;
4. treat uncertainty or missing/contradictory evidence as non-satisfied or
   uncertain;
5. approve only when every criterion is satisfied and no material finding remains.

Changing this policy changes the request identity and invalidates an old verdict.

## Structured verdict

`kaliv-development-semantic-review-verdict/v1` binds:

- request, receipt, patch, execution-authority and policy hashes;
- separate developer and reviewer actor IDs;
- reviewer-system ID;
- an explicit independence flag;
- `approve`, `request_changes` or `reject`;
- one ordered assessment for every acceptance criterion;
- bounded structured findings with severity, title and detail.

Each criterion assessment identifies the exact criterion by a domain-separated
SHA-256 and records `satisfied`, `not_satisfied` or `uncertain` plus rationale.
Every criterion must appear exactly once and in task order.

An approval is structurally valid only when every criterion is satisfied and the
finding list is empty. A non-approval cannot masquerade as a clean approval, and a
rejection requires at least one finding.

## Reviewer authentication

`kaliv-development-signed-semantic-review-verdict/v1` wraps the verdict with:

- reviewer key ID;
- `hmac-sha256` algorithm identity;
- a domain-separated signature over canonical verdict JSON.

The signer binds a key to one reviewer actor. The verifier uses a separate trusted
keyring that also binds each key ID to one actor. Verification fails on:

- unknown key;
- wrong reviewer actor;
- developer/reviewer identity reuse;
- invalid signature;
- changed request, patch, receipt, task, policy or execution authority;
- incomplete or reordered criterion assessments.

HMAC is suitable only while the reviewer secret is held outside the developer and
execution workspace. Copying the review key into the execution side destroys the
independence claim. A later deployment may replace HMAC with an asymmetric or
service-authenticated mechanism without weakening the artifact binding.

## Offline exchange

The module provides canonical, create-once file helpers for review requests and
signed verdicts. They require absolute regular link-free paths, bounded UTF-8 JSON,
exact canonical bytes and non-existing output destinations. Files with trailing
newlines, reordered JSON representation, links or overwrite attempts fail closed.

A typical operating split is:

1. execution operator writes the canonical request to a review drop;
2. independent reviewer loads only that request and performs semantic analysis;
3. reviewer emits structured assessments and findings;
4. reviewer-only signer authenticates the verdict;
5. control-plane verifier reloads the exact request and signed verdict;
6. the approval gate returns true only for a fully verified `approve` verdict.

No transport, queue, model API or provider integration is included in Slice 10H.

## Relationship to Tier-A authority

The semantic-review module is intentionally outside the Tier-A v6 execution bundle
and is not exported through the Tier-A execution facade. It cannot issue leases,
build launch plans, stage runtimes, invoke `run_verified_tier_a_command`, reset Git
or produce a Tier-A receipt.

It instead stores and later re-verifies the exact v6 execution-authority hash. If
the execution code changes, even while a reviewer produces a freshly valid
signature over an altered request, verification against the current control-plane
root fails.

This separation avoids silently granting process authority to review-policy or
review-provider changes.

## Proofs

Portable adversarial tests prove:

- canonical request, verdict and signed-verdict round-trip;
- exact patch, receipt, task, policy and authority binding;
- schema field parity;
- separate developer/reviewer actors;
- reviewer-key-to-actor binding;
- invalid and unknown signatures fail closed;
- changed patch bytes, receipt hash, task or authority fail closed;
- uncertain assessments or findings cannot pass the approval gate;
- canonical files are create-once and noncanonical input is rejected;
- request construction exposes no workspace, command, argument, catalog or
  toolchain selection surface.

The full repository, native Windows isolation, Android, desktop, DPAPI and browser
contracts remain unchanged and continue to pass. Slice 10H does not require a new
physical I0b campaign because it does not modify the v6 execution-authority bundle.

## Deliberate limits

Slice 10H does not provide:

- an actual AI/model-provider adapter or claim that semantic analysis occurred;
- automatic trust in a reviewer merely because a signature is valid;
- reviewer-key provisioning or hardware-backed key custody;
- freshness, expiry or revocation distribution for reviewer keys;
- workspace access, code execution or test reruns by the reviewer;
- branch push, PR creation/update, merge, release, settings or deployment
  authority;
- runtime activation or unattended self-development.

The next safe integration is to require one verified Slice 10H approval in a
canonical draft-PR readiness/proposal artifact while retaining human merge
authority and no GitHub write capability.
