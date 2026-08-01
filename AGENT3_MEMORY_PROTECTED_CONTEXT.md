# T-033 protected local memory context

**Status:** dormant local-only compiler boundary. The protected store can be selected by the landed authenticated gateway/store slice, but this compiler is not injected into production startup, planner routes, normal chat or any API surface.

## Privacy contract

`ProtectedMemoryContextCompiler` accepts only `ContextTarget.LOCAL`. A cloud target is rejected before the reader decrypts any envelope, and there is no private-cloud override.

The compiler:

- requires a real `ProtectedMemoryReader` opened against a completed migration;
- requests exact `MemoryReadAccess.LOCAL_CONTEXT`;
- filters secret rows in SQL before decryption;
- bounds candidate reads to a 1–8 multiplier, at most 200 rows and 50,000 candidate characters;
- separately bounds final output to at most 50 records and 12,000 characters;
- accepts only active, confirmed, unexpired public/operational/private records;
- fails closed on secret sensitivity, source provenance, duplicate identity or unsupported state;
- reuses the existing untrusted-memory JSON renderer and markup escaping;
- returns a plaintext-free receipt containing IDs, counts, target, character count and SHA-256 only;
- always reports `secret_included=false`, `source_provenance_included=false` and `production_activation=false`.

A zero character or record budget returns an empty local context without opening an envelope.

## Dormancy contract

The module declares:

- `PROTECTED_CONTEXT_BOUNDARY = "dormant-local-only"`;
- `PRODUCTION_MOUNT = False`;
- `CLOUD_CONTEXT_ALLOWED = False`.

A dedicated static mutation gate verifies those markers and rejects imports from `production_mount.py`, `memory_surface.py`, `planner.py` or outcome boundaries. Promotion therefore requires a separate reviewed slice rather than a silent import.

## Adversarial coverage

The repository and Windows fixtures prove:

- private values may enter only the local untrusted-data block;
- secret, pending, unrelated-subject and source-provenance markers never appear;
- candidate decryption is bounded before final rendering;
- prompt/markup-looking values remain escaped JSON data;
- receipts contain hashes and identifiers, never protected plaintext;
- cloud refusal performs zero envelope opens;
- duplicate/non-canonical subjects, invalid budgets and a closed reader fail closed;
- real current-user Windows DPAPI can reopen a private value locally while keeping secret and provenance markers out of context and receipt.

## Deliberate remaining boundaries

- no planner or production-mount injection;
- no remote context-preview, cloud memory, secret reveal, embeddings or outcome injection;
- no automatic migration, key rotation, backup/restore operation, release or production activation;
- legacy remains the default store mode;
- protected planner memory remains disabled by the landed mount contract.
