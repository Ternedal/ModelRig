# H10D — Durable semantic-review publication

H10D moves the supported semantic-review artifact writers to the shared
`durable_publication.create_once_file()` boundary.

## Covered artifacts

The public `kaliv_dev_control.semantic_review` module durably publishes:

- `SemanticReviewRequest`; and
- `SignedSemanticReviewVerdict`.

Their schemas, canonical UTF-8 JSON, embedded Tier-A receipt, staged-patch
bytes, HMAC verdict signature and SHA-256 identities are unchanged.

## Publication contract

Both writers:

- require an absolute destination below an existing link-free directory;
- reject an existing destination or symlink;
- publish with no-replace create-once semantics;
- make the file and parent-directory entry durable;
- translate publication races and durability failures to
  `SemanticReviewError`; and
- return the SHA-256 of the exact canonical bytes that were published.

The writers do not create a workspace, run a command, select a runtime,
contact a network service or mutate Git or GitHub state.

## Compatibility boundary

The pre-H10D semantic-review model, signer and verifier implementation is
retained byte-identically in the underscore-marked
`kaliv_dev_control._semantic_review_core` module. The public facade re-exports
the same class objects, constants, loaders and verification functions, so
canonical artifacts and `isinstance` identities remain stable.

The public `tier_a_toolhost_sha256` patch point remains effective for existing
offline fixtures. The superseded `_write_canonical_file()`,
`write_semantic_review_request()` and
`write_signed_semantic_review_verdict()` symbols are removed from the loaded
core namespace; the public facade owns the only supported publication path.

The retained core source still contains the historical writer text as part of
the byte-identical pre-H10D model snapshot. It is not exported or callable
through the loaded core namespace after the public boundary is imported. A
future module-splitting cleanup may remove that dead source without changing
canonical models or artifacts.

## Failure behavior

Publication fails closed when:

- the destination is relative;
- the destination or any parent component is link-like;
- the destination already exists;
- another writer wins the create-once race; or
- file or directory durability cannot be established.

No replacement write is attempted and no sibling temporary artifact remains.

## Verification

H10D tests apply the same contract independently to the request and signed
verdict. They prove:

- byte-identical publication and canonical reload;
- exactly one winner across 24 concurrent writers per artifact type;
- rejection of every losing writer;
- no leftover sibling artifacts;
- fail-closed injected durability failure;
- symlink rejection;
- preserved public model identity and authority patch point; and
- absence of `tempfile.mkstemp()`, `os.replace()` and `os.fsync()` from the
  supported public module.

## Authority boundary

H10D adds no credential, token, private-key loader, subprocess, Git command,
remote, socket, HTTP client, GitHub writer, branch push, pull-request creation
or mutation, reviewer request, ready-for-review conversion, merge, release,
settings, deployment or production authority.
