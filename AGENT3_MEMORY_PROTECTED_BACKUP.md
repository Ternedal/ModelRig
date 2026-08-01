# Agent 3 protected memory backup/restore — T-033

**Status:** dormant storage boundary. This slice does not run at worker startup,
create a scheduled/cloud backup, replace the active database, rotate a key or
claim a physical Windows-rig restore.

## Bundle format

`ProtectedMemoryBackupManager.create()` writes one new directory containing
exactly:

- `memory.sqlite3` — a consistent SQLite backup containing the protected
  envelopes, not decrypted values;
- `manifest.json` — schema `kaliv-agent3-memory-protected-backup/v1`.

The bundle is written to a random temporary sibling and becomes visible only by
an atomic directory rename. An existing bundle is never overwritten.

The manifest contains:

- format revision and creation time;
- completed migration schema/id;
- provider and key scope;
- protected/redacted/public-operational row counts;
- database SHA-256, byte count and SQLite page geometry;
- at most three protected memory ids used for bounded restore verification;
- an explicit policy requiring an absent destination, the same provider and key
  scope, bounded key-open verification and later physical Windows restore;
- `production_activation=false`.

It never contains protected values, protected `source_ref` values or decrypted
receipts.

## Backup boundary

A source can be backed up only when `ProtectedMemoryReader` accepts it:

- migration is completed and scrubbed;
- private/secret plaintext columns are empty;
- every protected row has exact schema/provider/key-scope metadata;
- public/operational rows have no partial protection metadata;
- the injected codec matches the store.

SQLite's backup API copies one consistent snapshot, including committed WAL
state. The copy is normalized to a single-file DELETE-journal database, checked
with `PRAGMA integrity_check`, reopened through the protected reader and hashed
before the manifest is written.

Backup does not decrypt any value. It does not search values, write an index or
create a readable duplicate.

## Verification boundary

`verify()` independently reopens the bundle and rejects:

- unknown or extra manifest keys;
- schema/revision/policy drift;
- wrong provider or key scope;
- missing, extra, symlinked or irregular bundle entries;
- artifact digest, byte-count or SQLite page-geometry drift;
- invalid/moved verification ids;
- incomplete migration, restored plaintext or corrupt SQLite.

The producer's result is never trusted without this revalidation.

## Atomic restore boundary

`restore()` requires a destination path that does not exist. It copies the
validated artifact to a random temporary sibling and keeps the final destination
absent until all checks pass.

Before the atomic rename it:

1. revalidates the restored SQLite store;
2. reruns `integrity_check` and page-geometry checks;
3. opens at most three manifest-bound protected rows through exact
   `LOCAL_MANAGEMENT` access;
4. discards the values without returning or logging them.

The bounded open proves that a provider with the same textual id but the wrong
key cannot restore the bundle. On failure, the temporary database/WAL/SHM/journal
family is removed and an existing destination is never touched.

A store with no protected rows can be structurally restored, but cannot prove a
key-open. The physical T-033 ceremony must therefore include at least one known
private/secret canary.

## CI evidence

The auto-globbed test suite uses an authenticated injected provider to cover:

- ciphertext-only backup and same-key restore;
- private/secret/source canaries absent from bundle bytes;
- wrong-key restore leaving no destination;
- existing destination/bundle refusal;
- incomplete migration refusal;
- artifact tamper, manifest drift, extra files and verification-id drift;
- single-file restored SQLite output.

The dedicated `agent3-memory-backup-windows` workflow repeats the complete
fixture with real Windows DPAPI current-user and proves private plus secret values
reopen under the same runner user.

## Remaining physical acceptance

CI is not the Windows rig. T-033 remains open until a later physical operator:

- creates a bundle from the exact rig candidate under the real Windows user;
- archives/hashes it without exposing the canary;
- restores to a new local database path;
- reopens the private/secret canary under the same user;
- proves a different Windows user/profile cannot open it;
- verifies SQLite/WAL/backups/logs/previews contain no canary plaintext;
- records exact candidate, artifact and observation hashes.

No merge, release or production activation is implied by a green software or CI
result.
