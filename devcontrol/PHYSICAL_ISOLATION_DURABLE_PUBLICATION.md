# Durable physical-isolation evidence publication (DC-L04)

DC-L04 publishes one canonical signed Windows physical-isolation evidence
artifact through the shared crash-durable create-once primitive.

## Publication contract

`write_signed_report()`:

1. accepts only an exact `SignedWindowsIsolationReport`;
2. requires an absolute output path below an existing link-free directory;
3. rejects an existing output, symlink, junction or reparse-point component;
4. serializes canonical UTF-8 JSON;
5. enforces the physical-evidence byte bound;
6. publishes through `durable_publication.create_once_file()`;
7. translates replacement races and durability failures to
   `PhysicalIsolationError`; and
8. returns the SHA-256 of the exact published bytes.

The shared primitive supplies no-replace create-once semantics, file durability
and parent-directory durability. Concurrent publishers can produce exactly one
winner and no temporary sibling is retained.

## Evidence boundary

The report and detached HMAC signature are evidence contracts only. They do not
implement Windows Job Objects, AppContainer, ACL provisioning, process launch or
catalog activation. Those runtime capabilities are deferred to later slices.

The signing key is an external operator-custody boundary. On POSIX the loader
requires an owner-only regular file in an owner-controlled non-writable directory.
On Windows DC-L04 fails closed until a native owner/DACL handle verifier is
available.

A valid signed artifact proves exact report/key binding, not that the physical
probes were honestly performed. Separate collection and approval actors, the
eleven required probe receipts and operational key custody remain external
physical controls.

## Verification coverage

The portable regressions require:

- byte-identical canonical publication and stable signed-report identity;
- exactly one winner under concurrent publication;
- no final artifact after injected durability failure;
- bounded stable no-follow reads for unsigned reports and evidence candidates;
- restrictive operator-key custody;
- rejection of links, junction-like components, special files, replacement races,
  stale/future evidence, duplicate candidates and non-canonical JSON; and
- preservation of DC-L03's empty, non-launchable catalog boundary.

No GitHub write, remote Git, pull-request mutation, merge, release, deployment or
activation authority is added.
