# T-033 protected local memory context

**Status:** dormant compiler boundary. It can compile a bounded local context from
an explicitly opened protected reader, but production startup/planner does not
select it in this slice.

## Privacy contract

`ProtectedMemoryContextCompiler` accepts only `ContextTarget.LOCAL`.
A cloud target is rejected before the reader decrypts any envelope. There is no
`allow_private_cloud` override.

The compiler:

- requires a real `ProtectedMemoryReader` opened against a completed migration;
- requests exact `MemoryReadAccess.LOCAL_CONTEXT`;
- filters secret rows in SQL before decryption;
- retrieves at most a bounded candidate set (default four times the final record
  limit, never more than 200 rows or 50,000 candidate characters);
- includes only active, confirmed, unexpired public/operational/private records;
- rejects any candidate that contains secret sensitivity, source provenance,
  unsupported state or duplicate identity;
- applies the existing untrusted-memory renderer and its final character/record
  budget;
- escapes angle brackets and ampersands so stored text cannot visually close the
  memory envelope;
- returns a receipt containing IDs, counts, target, character count and SHA-256
  of the compiled block — never values or source references;
- always reports `secret_included=false`,
  `source_provenance_included=false` and `production_activation=false`.

A zero character/record budget returns a truly empty context without opening an
envelope.

## Adversarial coverage

The auto-globbed fixture proves:

- private values may appear in the local untrusted data block;
- secrets, pending records, unrelated subjects and protected source references
  never appear;
- candidate decryption is bounded before final rendering;
- prompt/markup-looking values remain escaped JSON data;
- the receipt contains hashes/IDs only;
- cloud target, duplicate/non-canonical subjects, invalid budgets and a closed
  reader fail closed;
- cloud refusal performs zero decryptions.

The dedicated Windows protected-store workflow migrates a real SQLite fixture
with DPAPI current-user protection and compiles the private value locally while
keeping secret and provenance out of both context and receipt.

## Promotion boundary

This slice does not modify `production_mount.py`, `planner.py`, any API route or
normal chat. Protected mode in draft PR #208 therefore still returns
`memory planning is not mounted` when `use_memory=true`.

A later promotion must deliberately inject this compiler into the planner and
compose it with draft PR #206's leak-surface gate. It must preserve local-only
routing, secret/provenance exclusion, bounded decrypt and plaintext-free receipts.
