# Agent 3 memory protection — T-033

**Status:** dormant format/provider slice. The current `MemoryStore` still writes
`agent_memories.value` and `source_ref` as plaintext. Nothing in this slice
migrates a row, changes an API response, enables secret context, creates an
embedding or claims physical Windows backup/restore evidence.

## Delivered contract

`worker/app/agent3/memory_protection.py` defines one strict envelope family:

```text
kaliv-agent3-memory-protection/v1
```

The canonical JSON envelope contains exactly:

- schema;
- provider identity;
- OS key scope;
- text encoding;
- SHA-256 of the exact row/field scope;
- SHA-256 of the ciphertext;
- base64 ciphertext.

Unknown or missing fields are rejected. The format never stores the memory ID,
subject, predicate, plaintext, source reference or an unhashed copy of the scope.

## Protected scope

The first format supports fields classified as `private` or `secret`. Public and
operational values are deliberately refused by this codec rather than silently
being encrypted under an ambiguous policy.

Ciphertext is bound to all of these facts:

- memory ID;
- subject;
- predicate;
- sensitivity;
- protected field (`value` or `source_ref`);
- memory row schema version.

Moving a valid envelope to another row, field, sensitivity or schema version
therefore fails before plaintext is requested from the provider.

## Windows provider

`WindowsDpapiMemoryProtectionProvider` uses Windows DPAPI with:

- current-user scope;
- `CRYPTPROTECT_UI_FORBIDDEN`;
- exact row/field scope supplied as optional entropy;
- no machine-scope flag;
- no fallback to plaintext or a portable key.

Linux CI validates the format through an injected authenticated test provider.
A dedicated `windows-latest` job executes the same adversarial suite plus a real
DPAPI roundtrip and authenticated-tamper rejection.

This is CI evidence about the Windows API contract, not physical rig evidence.
The T-033 acceptance criterion for backup/restore and user scope still requires
the selected Windows validation candidate.

## Fail-closed behavior

The contract rejects:

- unknown schemas, providers, key scopes and encodings;
- unknown or missing envelope fields;
- malformed hashes and base64;
- ciphertext digest drift;
- provider authentication failure;
- wrong memory/field scope;
- invalid UTF-8 after decryption;
- empty and oversized plaintext/ciphertext/envelopes;
- provider construction outside Windows for the production DPAPI adapter.

The metadata projection exposes hashes and byte counts only. It never returns the
ciphertext body or original memory value.

## Explicit non-goals in this slice

- no change to `agent_memories` schema;
- no automatic migration or rotation;
- no search index over protected values;
- no API/client integration;
- no logs, previews, embeddings or outcome-context integration;
- no key escrow or cross-user restore;
- no production activation.

## Required follow-up slices

1. Add a resumable SQLite schema migration with separate envelope columns and no
   readable duplicate of protected values.
2. Make the authorized memory boundary decrypt only after row/scope validation;
   list/search/context must not accidentally scan protected plaintext.
3. Add resumable rotation and backup/restore receipts.
4. Prove on the physical Windows candidate that another user/scope cannot open
   the value and that approved restore behavior is truthful.
5. Add leak tests across logs, previews, embeddings and outcome context.

T-033 remains open until those slices and the physical Windows evidence are green.
