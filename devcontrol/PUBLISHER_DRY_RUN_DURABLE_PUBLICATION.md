# Durable publisher dry-run artifact publication (H10C)

H10C migrates the three canonical publisher dry-run artifact writers to the
shared crash-durable create-once publication primitive:

- `write_publisher_request()`;
- `write_signed_publisher_request()`; and
- `write_publisher_dry_run_receipt()`.

The request, signed request and dry-run receipt models, JSON schemas, canonical
serialization, signatures, operation plan and SHA-256 identities are unchanged.
The change affects only publication of already constructed local artifacts.

## Publication contract

The shared `_write_canonical()` path now:

1. requires an object with canonical JSON serialization;
2. requires an absolute output path under an existing link-free directory;
3. rejects an existing output path or symlink;
4. preserves the existing 64 MiB artifact bound;
5. publishes through `durable_publication.create_once_file()`;
6. translates publication races and durability failures to
   `PublisherDryRunError`; and
7. returns the SHA-256 of the exact published canonical UTF-8 bytes.

The shared primitive provides no-replace create-once semantics, file durability
and parent-directory durability. A concurrent caller cannot replace the winning
request, signed request or receipt.

## Verification coverage

H10C tests apply the same contract independently to all three artifact types and
require:

- byte-identical canonical output and unchanged artifact hashes;
- successful canonical reload after publication;
- exactly one winner across 24 concurrent publication attempts;
- rejection of every losing concurrent attempt;
- no leftover temporary or sibling artifact;
- fail-closed behavior with no output when durable publication is injected to
  fail;
- rejection of a symlink output path; and
- physical absence of the former `tempfile.mkstemp()` plus `os.replace()` writer
  implementation.

## Authority boundary

These remain local dry-run evidence writers. H10C adds no credential, token, new
signer, private-key loader, subprocess, Git command, remote, socket, HTTP client,
GitHub writer, branch push, pull-request creation or mutation, reviewer request,
ready-for-review conversion, merge, release, settings, deployment or production
authority. `merge_authority` remains human-only.
