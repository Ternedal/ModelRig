# Durable draft-PR readiness publication (H10)

H10 migrates the canonical authenticated draft-PR readiness proposal writer to
the shared crash-durable create-once publication primitive.

The proposal model, JSON schema, canonical serialization and SHA-256 identity are
unchanged. The change affects only how the already constructed local artifact is
published.

## Publication contract

`write_authenticated_draft_pr_readiness_proposal()` now:

1. accepts only an exact `AuthenticatedDraftPrReadinessProposal`;
2. requires an absolute output path under an existing link-free directory;
3. rejects an existing path or symlink;
4. serializes the same canonical UTF-8 JSON bytes as before;
5. enforces the existing 56 MiB artifact bound;
6. publishes through `durable_publication.create_once_file()`;
7. translates publication races and durability failures to
   `DraftPrReadinessError`; and
8. returns the SHA-256 of the exact published bytes.

The shared primitive provides no-replace create-once semantics, file durability
and parent-directory durability. A concurrent caller cannot overwrite the
winner's artifact.

## Verification coverage

H10 tests require:

- byte-identical canonical output and an unchanged proposal hash;
- successful canonical reload after publication;
- exactly one winner across 24 concurrent publication attempts;
- rejection of every losing concurrent attempt;
- no leftover temporary or sibling artifact; and
- fail-closed behavior with no output when durable publication is injected to
  fail.

## Authority boundary

This remains a local evidence writer. H10 adds no credential, token, signer,
private-key loader, subprocess, Git command, remote, socket, HTTP client, GitHub
writer, pull-request mutation, reviewer request, ready-for-review conversion,
merge, release, settings, deployment or production authority.
