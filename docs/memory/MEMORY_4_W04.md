# Memory 4.0 W04 — default-off completed-turn write surface

Status: W04-A is a default-off, loopback-only experimental worker surface. It does not intercept normal chat and does not activate production memory writes.

`production_activation=false`

## Purpose

W03 provides an in-process composition from one completed turn to W01 extraction and fresh transactional W02 writes. W04-A makes that composition independently testable through the worker HTTP process without turning it into normal-chat behavior.

The surface exists only after exact opt-in:

- flag: `KALIV_MEMORY4_WRITE_ENABLED=1`;
- route: `POST /experimental/memory4/completed-turn`;
- default: disabled.

The write flag is independent from `KALIV_MEMORY4_CONTEXT_ENABLED`, `KALIV_MEMORY4_CHAT_ENABLED` and `KALIV_AGENT3_ENABLED`. With the write flag disabled, worker startup returns before constructing a W04 storage writer or protected-memory provider and registers no W04 route.

## HTTP authority boundary

The route is loopback-only and fail-closed. The request body has exactly three bounded string fields:

- `user_text`;
- `assistant_text`;
- `source_ref`.

Unknown fields and non-string values are rejected by the strict request model. W03 applies the canonical W01 completed-turn bounds and authority rebinding again before any candidate batch can reach storage.

The response is only the value-free W03 receipt. It may contain schema, counts, durable ids, replay state and `sent_to_store`, but it has no representation for candidate values, extraction evidence, `source_ref`, raw model output, encryption envelopes or blind-index fingerprints.

Operational extraction/write/storage failures return a fixed `503` response (`memory write unavailable`). Exception messages and types are not reflected through the route.

## Extraction

Production composition injects the existing `extract_memory_candidates_local` W01 adapter. That adapter permits only a loopback Ollama upstream and has no cloud fallback.

W04-A adds no model selection route, cloud extractor, private-cloud grant or caller-supplied write operation.

## Storage modes

W04-A uses the existing `KALIV_AGENT3_MEMORY_STORE` selection and the same durable database path as the current memory substrate.

### Legacy

Legacy mode owns a process-local `MemoryStore` and commits candidate batches only through `commit_legacy_candidates(...)`. W02 replans against current durable state under the write transaction before mutation.

### Protected

Protected mode requires the existing completed protected-memory migration before the writer opens. Candidate batches are committed through `commit_protected_candidates(...)` with exact `MemoryWriteAccess.LOCAL_MANAGEMENT` authority. Sensitive values and source references continue through the existing protection codec and are not written into plaintext base columns.

### Indexed protected

W04-A deliberately does **not** expose the indexed-protected W03 adapter. It therefore cannot create, migrate, repair or otherwise manage the #1218 blind-index sidecar. A later slice may expose that composition only behind its own explicit reviewed boundary.

## Mount, rollback and shutdown

Mounting is atomic with respect to the route and process-owned writer state:

- flag-off performs no storage/provider construction;
- mount failure removes any route added by that attempt and clears owned state;
- the process-owned writer is closed during worker lifespan shutdown;
- W04 cleanup is composed into the existing Memory4 context lifespan wrapper rather than introducing a competing lifespan layer;
- `scheduler_lifespan` remains the exact `__wrapped__` owner of the production wrapper.

## Qualification

Focused qualification is kept under `tests/support/` and invoked by the existing top-level Memory 4 storage test entrypoint. Coverage includes:

- write flag off while context/chat/Agent3 flags are on;
- no provider/DB/route construction while disabled;
- default binding to the local W01 extractor without calling it during mount;
- loopback denial before extraction/storage;
- strict unknown-field/type rejection;
- empty extraction with `sent_to_store=false`;
- value/source-ref absence from HTTP receipts;
- legacy create then exact dedupe;
- generic sanitized `503` on extraction failure;
- protected migration + encrypted write round-trip;
- plaintext absence from protected SQLite base columns;
- proof that W04-A does not create the blind-index sidecar;
- deterministic mount rollback;
- shutdown cleanup while preserving the existing scheduler lifespan wrapper contract.

## Deliberate non-goals

W04-A adds no:

- `/api/v1/chat` hook or stream interception;
- automatic write after assistant completion;
- queue, scheduler or background extraction;
- cloud model/extractor fallback;
- cloud/private-cloud memory write authority;
- Agent 3 activation dependency;
- user-facing review UI;
- blind-index migration/repair authority;
- production activation.

**W04-B remains required before normal chat may invoke W03 automatically after an assistant turn completes.** W04-A landing alone does not persist ordinary chat turns.
