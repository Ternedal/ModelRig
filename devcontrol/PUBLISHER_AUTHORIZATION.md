# Slice 10K — one-time publisher authorization and replay ledger

Slice 10K adds an authenticated, time-bounded and single-use authorization layer
over one exact Slice 10J signed publisher request. It remains an offline evidence
boundary. It does not contain a Git transport, GitHub API client, credential value,
network request or repository mutation adapter.

## Purpose

Slice 10J proves that a separately authenticated publisher intended one exact,
draft-only publication plan. Slice 10K adds the missing controls needed before any
future publication worker could safely consider that intent:

1. an independently signed authorization lease;
2. a fixed remote-repository identity;
3. a fixed least-privilege credential policy;
4. a strict issue/expiry window;
5. atomic one-time invocation-nonce consumption;
6. canonical preflight evidence; and
7. canonical no-execution postcondition evidence.

None of these artifacts performs the proposed operations.

## Artifact chain

The chain is:

```text
Slice 10I authenticated draft-PR readiness
  -> Slice 10J publisher request
  -> Slice 10J publisher signature
  -> Slice 10K authorization lease
  -> Slice 10K atomic replay-ledger entry
  -> Slice 10K preflight receipt
  -> Slice 10K no-execution postcondition receipt
```

Every later artifact embeds or hashes all earlier identities needed for independent
verification. The exact task, staged patch, semantic-review approval, proposed
branch, title/body, publisher actor, invocation nonce and current Tier-A v6
authority therefore remain transitively bound.

## Authorization issuer

The authorization issuer is a fourth actor. It must differ from:

- the developer actor in the semantic-review request;
- the semantic reviewer actor; and
- the publisher actor in the Slice 10J request.

`HmacPublisherAuthorizationIssuer` uses a domain-separated HMAC-SHA256 key bound
to the exact issuer actor. The key is an authorization-signing key only. It is not
a GitHub credential and grants no network or repository authority.

A valid lease signature proves possession of the trusted issuer key and exact
artifact binding. It does not prove that a biological human approved the lease,
that the repository identity was independently looked up, or that the issuer key
is stored in hardware. Those stronger claims require an external operating
boundary.

## Remote repository identity

`RemoteRepositoryIdentity` binds:

- provider: `github`;
- host: `github.com`;
- exact `owner/repository` name; and
- an immutable numeric repository ID supplied by trusted configuration.

The repository name must equal the repository already derived by Slice 10I and
bound by Slice 10J. Slice 10K does not contact GitHub to discover or validate the
numeric ID. Production provisioning must obtain and protect that identity outside
the developer workspace.

## Least-privilege credential policy

The lease embeds a canonical policy and its SHA-256. The policy permits only the
future capabilities required by the exact Slice 10J plan:

- contents write for the exact proposed branch only; and
- pull-request write for creation of the exact draft only.

It explicitly denies administration, Actions/workflows, base-branch writes,
checks, deployments, environments, force-push, issues, members, merge, packages,
pages, ready-for-review, release, repository settings, reviewer requests,
secrets/variables, tag writes and webhooks.

The policy also requires:

- exact branch scope;
- draft-PR-only scope;
- maximum use count of one;
- no reusable credential; and
- no credential or token material in the artifact.

The current module defines and hashes this policy but does not provision or use a
credential.

## Lease validity

`kaliv-development-publisher-authorization-lease/v1` embeds the complete signed
Slice 10J request and binds:

- signed request, request, readiness and task hashes;
- exact invocation nonce;
- complete remote-repository identity and hash;
- complete credential policy and hash;
- fixed authorization-policy hash;
- canonical issue and expiry timestamps;
- issuer actor, system and key IDs;
- HMAC algorithm and signature;
- `one_time: true`;
- `maximum_uses: 1`;
- `draft_only: true`; and
- `merge_authority: human`.

Timestamps use canonical UTC seconds (`YYYY-MM-DDTHH:MM:SSZ`). A lease must last at
least one second and no more than fifteen minutes. Verification is valid at the
issue timestamp and fails at or after the expiry timestamp.

The verifier rechecks:

- the issuer signature and actor-bound trusted key;
- the complete Slice 10J publisher signature;
- the complete Slice 10I readiness artifact;
- the trusted semantic-review signature;
- the exact task; and
- the current Tier-A v6 execution-authority hash.

## Atomic replay ledger

`PublisherReplayLedger` is a link-free absolute directory containing one immutable
canonical entry per invocation nonce. It deliberately does not use a mutable JSON
status file.

Nonce consumption uses the operating system's exclusive create operation:

```text
O_CREAT | O_EXCL
```

The filename is derived only from the already validated 64-character hexadecimal
invocation nonce. Therefore:

- sequential reuse fails;
- two concurrent consumers cannot both succeed;
- an existing malformed or attacker-created entry still blocks reuse fail-closed;
- no stale writer can overwrite a successful consumption; and
- no mutable in-memory set is treated as durable replay protection.

The created `kaliv-development-publisher-replay-ledger-entry/v1` embeds the full
lease and binds the lease, signed request, request, nonce, remote identity,
credential policy, ledger ID, consumption time and publisher actor. Consumption
must occur inside the lease window.

The ledger directory itself is a trusted operating boundary. Slice 10K does not
protect it against a separate administrator or kernel component, replicate it, or
provide multi-host consensus.

## Preflight receipt

`kaliv-development-publisher-preflight-receipt/v1` can be created only after:

- the authorization lease verifies at the explicit check time; and
- the exact invocation nonce has a matching canonical replay-ledger entry.

It binds the lease, replay entry, complete upstream identity chain, remote
repository, credential policy and the five exact Slice 10J operations.

The receipt requires:

- valid lease;
- consumed nonce;
- matching remote identity;
- matching credential policy;
- exact draft-only scope;
- no credential material;
- no write adapter;
- no repository write; and
- no network write.

`PublisherPreflightGate` re-verifies the chain rather than trusting Boolean fields
alone.

## Postcondition receipt

Slice 10K does not have an executor or observer, so it cannot honestly claim that a
commit, branch, push or pull request exists. Its
`kaliv-development-publisher-postcondition-receipt/v1` therefore has one valid
state only:

```text
execution_state: not_executed
```

It requires all repository/network observation and result fields to remain false,
including commit creation, branch creation, push, pull-request creation,
ready-for-review, reviewer requests, merge, release and deployment.

This artifact is a deterministic no-execution receipt and a schema boundary for a
future separately reviewed worker. It is not evidence of successful publication.

## Canonical storage

Lease, replay-entry copies, preflight receipts and postcondition receipts support
bounded canonical JSON load/write helpers. Outputs require:

- absolute paths;
- regular, link-free parents;
- create-once semantics;
- atomic temporary-file replacement; and
- exact canonical UTF-8 bytes with no trailing newline.

The replay ledger uses stronger direct exclusive creation rather than temporary
replacement because uniqueness is the security property.

## Deliberately absent authority

Slice 10K still cannot:

- discover or validate the remote repository through a network call;
- provision, store, rotate, revoke or use a GitHub credential;
- execute Git;
- materialize a commit;
- create or update a branch;
- push a branch;
- create or update a pull request;
- request reviewers;
- mark a pull request ready for review;
- merge;
- create releases or tags;
- change settings, secrets, variables, workflows or webhooks;
- deploy; or
- activate unattended self-development.

The module remains outside the Tier-A v6 execution bundle. No new physical I0b
campaign is required for this downstream evidence-only slice.

## Schemas

- `schemas/development-publisher-authorization-lease-v1.schema.json`
- `schemas/development-publisher-replay-ledger-entry-v1.schema.json`
- `schemas/development-publisher-preflight-receipt-v1.schema.json`
- `schemas/development-publisher-postcondition-receipt-v1.schema.json`

## Adversarial proof

`tests/test_slice10k_publisher_authorization.py` proves:

- complete canonical round-trips and schema field parity;
- exact signed-request, task, nonce, remote and policy binding;
- issuer/developer/reviewer/publisher separation;
- wrong-secret, altered-signature and untrusted-key rejection;
- strict issue/expiry and fifteen-minute lifetime boundaries;
- exact expiry is invalid;
- remote-identity and permission-policy tampering fails closed;
- sequential replay fails;
- two simultaneous nonce consumers produce exactly one winner;
- preflight cannot omit or add operations;
- credential material and write-adapter claims fail closed;
- every unavailable postcondition/result flag fails when changed to true;
- another task and current execution-authority drift fail closed;
- canonical outputs cannot overwrite existing files; and
- the module exposes no live Git/GitHub/network writer surface.
