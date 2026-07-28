# Agent 3 protected memory writer — T-033

**Status:** dormant local-management write boundary. This slice is not selected by
worker startup and exposes no HTTP route. The existing `MemoryStore` remains
unchanged.

## Scope

`ProtectedMemoryWriter` writes only `private` and `secret` rows in a database that
already has a completed, scrubbed protection migration. It refuses public and
operational values instead of silently falling back to plaintext.

Every operation requires the exact enum value:

```text
MemoryWriteAccess.LOCAL_MANAGEMENT
```

Strings, implicit defaults and remote authorization claims are rejected. The enum
is a storage-boundary proof, not an authentication system.

## Create

A protected create:

1. validates subject, predicate, kind, sensitivity, provenance, confidence,
   review state and expiry;
2. assigns a fresh opaque row ID;
3. protects `value` and optional `source_ref` under separate row/field scopes;
4. inserts one row whose plaintext `value` is empty and plaintext `source_ref` is
   NULL;
5. validates the stored protection shape before commit.

Provider failure or ID collision commits no row. No temporary plaintext column,
shadow table or search index is created.

## Correct

A correction requires the caller's exact `expected_updated_at`. In one
`BEGIN IMMEDIATE` transaction it:

- validates the active protected row and migration receipt;
- rejects stale state;
- inserts a separately scoped protected replacement;
- supersedes the old row using the same compare-and-swap timestamp.

The old row remains encrypted history. A failed insert, provider call or CAS
rolls the full transaction back.

## Delete

Delete also requires exact `expected_updated_at`. It retains only lifecycle and
provenance metadata while clearing both envelopes and marking the row
`redacted`. SQLite `secure_delete=ON` is active on the writer connection.

A repeated or stale delete fails instead of being reported as a successful no-op.

## Validation

The Linux adversarial suite proves:

- create/correct/delete never populate plaintext columns;
- the protected reader opens committed values and source references through the
  existing access matrix;
- secret context remains redacted;
- correction history remains encrypted and ordered;
- stale correction/delete, access drift and public sensitivity fail closed;
- source-ref encryption failure and ID collision leave no partial row;
- known test plaintext is absent from SQLite/WAL/journal bytes;
- closed writers reject further operations.

The dedicated Windows workflow performs the fixture migration and protected
create/read cycle with real DPAPI current-user protection, then scans the SQLite
file family for the known values.

## Remaining work

- deliberate startup/store selection;
- API authorization and response redaction;
- review-state transitions through the protected writer;
- rotation and physical backup/restore evidence;
- leak tests across logs, previews, embeddings and outcome context;
- a privacy-reviewed value-search design, if value search remains required.

No production activation, route or automatic migration is introduced here.
