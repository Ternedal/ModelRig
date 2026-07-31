# Agent 3 protected memory reader — T-033

**Status:** dormant read-only runtime boundary. This slice does not replace the
existing `MemoryStore`, wire a route, migrate automatically or enable protected
memory in normal Agent 3 execution.

## Opening contract

`ProtectedMemoryReader` opens an existing database only when all of these are
true:

- the path is a non-empty regular file and not a symlink;
- SQLite can open it in URI `mode=ro`;
- `PRAGMA query_only=ON` is active;
- all migration columns exist;
- the migration receipt is `completed` with `scrub_completed=1`;
- provider and current-user key scope match the injected codec;
- no private/secret row retains readable `value` or `source_ref`;
- every private/secret row is `protected` or payload-free `redacted`;
- public/operational rows contain no partial protection metadata.

An incomplete or mixed database is rejected. There is no fallback to the old
plaintext store.

## Explicit access modes

Every read method requires a `MemoryReadAccess` value. Strings and implicit
defaults are rejected.

### `metadata_only`

- values are returned as `[redacted]`;
- source references are omitted;
- no envelope is opened;
- useful for inventory and lifecycle inspection without a decryption key.

### `local_context`

- public, operational and private values may be opened locally;
- source references remain omitted;
- secret values remain redacted;
- `context_records` requires this exact access mode and always excludes secret,
  pending, rejected, expired, deleted and superseded rows.

### `local_management`

- private and secret values may be opened;
- protected source references may be opened;
- secret rows can only be included when this exact mode is supplied.

This is a storage-boundary permission, not remote authorization. No HTTP route is
wired to it in this slice.

## Search boundary

`search_metadata` searches only normalized `subject` and `predicate` columns.
It does not:

- search the plaintext `value` column;
- decrypt candidate rows to search them;
- search envelope JSON or ciphertext;
- create a plaintext or deterministic value index.

A term that exists only inside a protected value therefore returns no match.
Value search needs a separate privacy-reviewed design.

## No writes

The class exposes no `create`, `correct` or `delete` methods. Its SQLite
connection is query-only, and the test suite proves a direct SQL update fails.
New protected writes remain a separate T-033 slice.

## Validation

Linux CI uses an injected authenticated provider to test access, scope and
tamper behavior. A dedicated `windows-latest` workflow performs the same fixture
migration with real Windows DPAPI and proves private value plus protected
`source_ref` can be opened through the intended modes.

The reader fails closed for:

- incomplete migration;
- wrong provider identity;
- wrong provider key at reveal time;
- restored plaintext;
- changed row scope;
- authenticated ciphertext tamper;
- secret access outside local management;
- string/implicit access values;
- writes on the query-only connection;
- reads after close.

## Remaining work

- encrypted create/correct/delete transactions;
- deliberate worker/startup selection after migration;
- route and local-context integration without remote secret reveal;
- a privacy-safe search strategy, if value search remains required;
- rotation and physical Windows backup/restore evidence;
- leak tests for logs, previews, embeddings and outcome context.

`production_activation=false` remains the operative boundary. T-033 stays open.
