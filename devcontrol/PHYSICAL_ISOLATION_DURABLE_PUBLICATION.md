# Durable physical-isolation evidence publication (H10B)

H10B migrates the signed Windows physical-isolation evidence writer to the
shared crash-durable create-once publication primitive.

The physical report model, signed-report model, JSON schemas, canonical UTF-8
serialization, detached HMAC and SHA-256 identity are unchanged. Only the local
publication mechanism changes.

## Publication contract

`write_signed_report()` now:

1. accepts only an exact `SignedWindowsIsolationReport`;
2. requires an absolute output path under an existing link-free directory;
3. rejects an existing output or symlink;
4. serializes the same canonical JSON bytes as before;
5. enforces the existing physical-evidence size boundary;
6. publishes through `durable_publication.create_once_file()`;
7. translates replacement races and durability failures to
   `PhysicalIsolationError`; and
8. returns the SHA-256 of the exact published canonical bytes.

The shared primitive provides no-replace create-once semantics, file durability
and parent-directory durability. A concurrent process cannot replace the
winning evidence artifact.

## Verification coverage

H10B tests require:

- byte-identical canonical output and an unchanged signed-report hash;
- canonical reparse of the published evidence;
- exactly one winner across 24 concurrent publication attempts;
- rejection of all losing attempts;
- no sibling or temporary artifact left behind;
- fail-closed behavior with no output when durable publication is injected to
  fail; and
- absence of the prior `tempfile.mkstemp()` and `os.replace()` writer path.

## Authority consequence

`physical_isolation.py` is included in the Tier-A authority bundle. This change
therefore changes the authority digest and intentionally makes earlier physical
I0b reports stale. It does not manufacture replacement evidence. A fresh
physical campaign is still required only after the authority code is frozen.

## Capability boundary

This remains a local evidence writer. H10B adds no credential, token, new
signer, private-key loader, subprocess, Git command, remote, socket, HTTP
client, GitHub writer, pull-request mutation, reviewer request,
ready-for-review conversion, merge, release, settings, deployment or production
authority.
