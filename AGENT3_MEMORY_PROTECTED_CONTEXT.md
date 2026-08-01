# T-033 protected local memory context

**Status:** conditionally mounted planner-only boundary. The protected store can
be selected only behind the global Agent 3 feature flag and exact `protected`
store mode. The compiler is injected into the planner through one reviewed
adapter; it is not exposed through normal chat, a preview API, outcome paths or
cloud routing.

## Privacy contract

`ProtectedMemoryContextCompiler` accepts only `ContextTarget.LOCAL`. A cloud
target is rejected before the reader decrypts any envelope, and there is no
private-cloud override.

The compiler:

- requires a real `ProtectedMemoryReader` opened against a completed migration;
- requests exact `MemoryReadAccess.LOCAL_CONTEXT`;
- filters secret rows in SQL before decryption;
- bounds candidate reads to a multiplier of the final request, never more than
  200 rows or 50,000 candidate characters;
- separately bounds final output to at most 50 records and 12,000 characters;
- accepts only active, confirmed, unexpired public/operational/private records;
- fails closed on secret sensitivity, source provenance, duplicate identity or
  unsupported state;
- reuses the existing untrusted-memory JSON renderer and markup escaping;
- returns plaintext-free receipt data containing IDs, counts, target, character
  count and SHA-256 only;
- never performs migration, fallback, remote disclosure or value search.

A zero character or record budget returns an empty local context without opening
an envelope.

## Planner promotion contract

The planner adapter declares:

- `PROTECTED_PLANNER_CONTEXT_CONTRACT = "kaliv-agent3-protected-planner-context/v1"`;
- `CLOUD_CONTEXT_ALLOWED = False`;
- `LEGACY_STORE_FALLBACK = False`;
- an exact candidate multiplier of two.

The authorized composition chain is:

1. `memory_surface.py` validates and opens the protected reader/writer;
2. it constructs `ProtectedPlannerMemoryContextProvider` over that same reader;
3. `production_mount.py` passes the neutral provider into `build_planner_router`;
4. the planner resolves its route before asking the provider to compile memory.

Direct imports from planner, production mount or outcome modules into the
protected compiler are rejected by a static mutation gate. Protected and legacy
planner sources cannot be configured simultaneously.

## Adversarial coverage

Repository and Windows fixtures prove:

- private values may enter only the local untrusted-data block;
- secret, pending, expired, superseded, unrelated-subject and provenance markers
  never enter the prompt;
- candidate decryption and final rendering are independently bounded;
- prompt/markup-looking values remain escaped JSON data;
- receipts and plan persistence contain hashes and identifiers, never protected
  plaintext;
- cloud routing and private-cloud consent fail before decrypt and before the
  planner model call;
- real current-user Windows DPAPI can reopen eligible private values locally;
- legacy mode remains unchanged and protected mode mounts no legacy context
  preview or plaintext planner store.

## Deliberate remaining boundaries

- no remote context preview, secret reveal, embeddings or outcome injection;
- no automatic migration, key rotation, backup/restore operation or recovery
  bypass;
- no normal-chat routing change;
- no release, physical-rig proof or production-readiness claim;
- `legacy` remains the default store mode.
