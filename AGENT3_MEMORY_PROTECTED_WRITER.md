# Agent 3 protected memory writer

## Scope

This slice adds an explicit, dormant writer for private and secret Agent 3
memory records after the protected SQLite migration has completed.

The existing `MemoryStore` remains unchanged. The protected writer is not
selected by worker startup, mounted in an API, connected to planner context,
or enabled by an environment switch.

## Access boundary

Every operation requires the exact enum value
`MemoryWriteAccess.LOCAL_MANAGEMENT`.

Strings, missing access and any future enum member fail closed.

Only `private` and `secret` sensitivities are accepted. Public and operational
records continue to belong to the legacy plaintext store until a separate,
reviewed runtime-selection decision exists.

## Create

A protected create:

1. validates the completed migration receipt inside the write transaction;
2. validates the provider identity and key scope;
3. protects the value and optional source reference before any insert;
4. inserts an otherwise normal memory row whose plaintext payload columns are
   empty/NULL;
5. stores the value and source reference under separate exact scopes;
6. revalidates the protected row shape before commit.

A provider error or ID collision rolls the complete transaction back.

## Correct

Correction is an atomic compare-and-swap operation:

1. the existing row must be active and protected;
2. `expected_updated_at` must exactly match the stored revision;
3. the replacement value/source are protected under the new row id;
4. the replacement row is inserted;
5. the old row is marked `superseded` and linked to the replacement;
6. both changes commit together.

The old protected history remains decryptable only under explicit local
management access. A stale correction leaves both rows unchanged.

## Delete

Delete also requires exact `expected_updated_at` compare-and-swap.

The row becomes a payload-free lifecycle tombstone:

- state becomes `deleted`;
- value and source plaintext stay empty/NULL;
- both protected envelopes and their metadata are cleared;
- value becomes the public redaction marker through the reader;
- no deleted secret/private payload remains decryptable.

Repeated delete and stale delete attempts fail closed.

## Transaction and storage rules

- WAL mode, foreign keys and `secure_delete=ON` are enabled.
- Every write starts with `BEGIN IMMEDIATE`.
- Migration receipt, provider and key-scope checks run inside the transaction.
- Provider/codec failures are normalized to `ProtectedMemoryWriteError`.
- No plaintext/deterministic index over value or source is created.
- The writer exposes no list/search/context or secret-reveal helper.

## Explicit non-claims

This slice does not claim:

- worker startup or protected-store selection;
- a route or remote authorization model;
- secret reveal over HTTP;
- planner/context, embedding or outcome integration;
- automatic migration, key rotation or recovery bypass;
- physical Windows backup/restore evidence;
- production activation.

The dedicated Windows workflow runs the protected reader and writer fixtures
against real current-user DPAPI, but that proves only software behavior under
the CI account. It is not a ModelRig physical-rig backup/restore claim.
