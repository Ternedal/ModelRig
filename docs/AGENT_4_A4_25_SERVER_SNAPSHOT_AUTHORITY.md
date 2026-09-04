# Agent 4 A4-25 — server-side snapshot authority

Status: **A4-25a activation guard + A4-25b immutable store + A4-25c caller-driven writer publication + A4-25d snapshot-bound server read/wire layer + A4-25e Android snapshot/race layer implemented and exact-head qualified on stacked dormant draft slices; physical acceptance and production activation remain separate and deferred**.

Issue: #458.

This architecture does not change the qualified A4-18 physical candidate and does not enable lifecycle orchestration. It defines and incrementally implements the consistency model required before any future production composition may expose Agent 4 lifecycle mutation and operator reads concurrently.

## Problem

The current B-reference persistence model has an intentional multi-stage write path.

`JsonCampaignRepository.save_with_projections()` atomically persists the authoritative `CampaignRecord` together with durable projection intents. `CampaignStateProjectionService.persist()` then reconciles those intents into the append-only timeline and acknowledges them afterwards. Evidence records are persisted in their own append-only store and bind to a verified timeline head.

That is crash-safe and recoverable, but it is not one cross-store transaction. A concurrent reader could otherwise observe, for example:

1. campaign state revision N+1 already durable;
2. the corresponding timeline projection still pending or only partly reconciled;
3. evidence still representing the previous verified timeline head.

A4-24 rejects contradictions visible in overlapping Android metadata. It does not make the campaign, timeline and evidence stores globally transactional.

The current production read product remains safe because A4-21 composes a narrow read-only context with no lifecycle scheduler/resource/handoff/recovery mutation authority. This document defines what must replace that restriction before concurrent writer + product-read activation is allowed.

## Decision

Future concurrent Agent 4 operator reads will use a **server-owned immutable operator snapshot projection**. The operator API must not read the mutable campaign repository, live timeline head and live evidence head independently once concurrent lifecycle mutation is enabled.

The authority consists of:

- immutable per-campaign snapshot blobs;
- immutable root snapshot manifests;
- one atomically replaced `current` pointer;
- a content-addressed `snapshot_id` returned by the server and required by related reads and paging continuations.

The **atomic current-pointer replacement is the read commit point**.

### Campaign snapshot blob

Each immutable campaign snapshot contains at least:

- schema/version;
- complete canonical `CampaignRecord` content for that revision;
- canonical campaign-record SHA-256;
- `state_revision`;
- timeline head sequence and hash;
- evidence head sequence and hash;
- latest evidence-bound timeline-head hash;
- campaign identity;
- content-derived campaign snapshot id.

The campaign record is copied into the immutable snapshot. This is required because the live campaign envelope is replaced on later lifecycle transitions, while timeline and evidence histories are append-only and can be safely read only up to the head captured by the snapshot.

### Root snapshot manifest

Each immutable root manifest contains at least:

- schema/version;
- monotonically increasing root sequence;
- parent root snapshot id or null for genesis;
- publication timestamp;
- sorted mapping from campaign id to immutable campaign snapshot id;
- content-derived root `snapshot_id`.

A campaign mutation publishes a new campaign snapshot and then a new root manifest that reuses unchanged campaign snapshot references. Campaign deletion removes the reference only from the new root manifest; retained historical roots remain self-contained.

## Writer commit protocol

Snapshot publication must be serialized by one server-side snapshot publisher owned by the canonical Agent 4 writer runtime.

For a lifecycle-visible change the publisher must:

1. persist authoritative campaign state plus projection intent(s);
2. reconcile the required projection intent(s) into the timeline;
3. verify the intended projection event(s) exist and no required projection intent for the published revision remains pending;
4. perform any evidence mutation that is part of the same product-visible commit;
5. verify the campaign record, timeline chain and evidence chain;
6. load the currently committed root manifest;
7. create the immutable campaign snapshot using the verified heads and canonical campaign record;
8. write and fsync the campaign snapshot before it can be referenced;
9. create the immutable next root manifest, reusing unchanged campaign references;
10. write and fsync the root manifest;
11. atomically replace and fsync the `current` pointer to the new root `snapshot_id`.

If the process crashes before step 11, the old root remains authoritative. If it crashes after step 11, every referenced immutable object must already be durable. Recovery may clean unreferenced immutable objects but must never infer a half-written root as committed.

A publisher must not create a root snapshot while required `pending_projections()` exist for the campaign revision being published.

### A4-25c implementation discipline

The stacked A4-25c implementation keeps publication explicitly caller-driven. `Agent4RuntimeContext` owns one publisher and exposes explicit publish/prune methods, but composition itself creates no snapshot directories, performs no publication, starts no timer/thread, and does not invoke publication from scheduler/recovery/lifecycle paths.

A publication captures the complete campaign set, validates each append-only timeline/evidence chain, rejects pending projections, verifies evidence bindings against timeline heads in the same capture, and performs optimistic revalidation before the immutable root commit. Unchanged content-addressed campaign blobs are reused; an unchanged complete mapping reuses the current root rather than manufacturing a new sequence. Retention/GC remains a separate caller action after the commit path.

A4-25c, the dormant A4-25d server read/wire slice and the dormant A4-25e Android consumer/race slice are repository-qualified. This still does not relax the production mount: production wiring and any physical acceptance remain separate deliberate activation work.

## Read protocol

A request that starts a new logical read obtains the current root pointer exactly once.

The server returns that root `snapshot_id`. Every related read uses the same immutable root:

- campaign list;
- campaign detail;
- timeline pages;
- evidence pages;
- evidence verification.

Timeline and evidence reads are truncated at the sequence/hash heads stored in the selected campaign snapshot, even if newer append-only entries now exist.

Campaign-list, timeline and evidence cursors must bind to the same root `snapshot_id` in addition to their existing content/hash position. A continuation with a different, unknown or expired snapshot id fails closed; it never silently restarts against the new current root.

A directly addressed detail request without an incoming snapshot id may acquire a fresh current root and return its id. All follow-up timeline/evidence/verification requests for that detail must then carry that same id.

The Android A4-24 contradiction detector remains useful defence-in-depth, but it is not the server's global atomicity mechanism.

### A4-25d implementation discipline

The stacked A4-25d implementation adds a **parallel dormant v2** read path rather than changing the already-qualified v1 product contract in place.

`Agent4SnapshotOperatorReadService` selects exactly one retained immutable root. Campaign records are loaded only from immutable campaign snapshot blobs referenced by that root. The live timeline and evidence stores are treated only as append-only history sources: reads are truncated at the sequence captured by the immutable campaign snapshot and the resulting prefix head hash must equal the captured hash before data is returned.

Existing v1 hash/content cursors are retained as inner cursor contracts and wrapped in a small root-bound envelope carrying the immutable `snapshot_id`. An explicit root and a bound cursor must agree. Campaign-list paging also retains its existing list-head cursor as a separately root-bound value because a mid-page cursor cannot reconstruct the final campaign identity. Timeline/evidence heads are derived server-side from the immutable campaign snapshot and cannot be widened by the caller.

The dormant v2 FastAPI adapter uses the existing experimental operator route shape and returns schema `modelrig-agent4/operator-api/v2`. Every successful response carries the authoritative `snapshot_id`. A syntactically valid but unavailable/expired root is wire-distinct as HTTP **410**; a resource absent from the selected retained root is **404**; malformed/mismatched cursor requests are **422**; integrity/storage/no-current failures are **503**.

The router is not mounted by production bootstrap in A4-25d. The backend runtime is unchanged; its existing authenticated GET forwarder is covered by a pass-through contract proving snapshot query bytes, worker status/body and v2 media type are not rewritten.

### A4-25e implementation discipline

The stacked A4-25e implementation adds a **parallel dormant Android v2 client** rather than changing the qualified v1 Android production path.

`Agent4SnapshotOperatorClient` treats the server-provided root as authority:

- a new detail or list flow may acquire one current `snapshot_id`;
- every related detail/timeline/evidence/verification request carries that same root explicitly;
- campaign-list continuation carries the root plus both server-provided root-bound `after` and list-head cursors;
- timeline/evidence continuation carries the root plus only the server-provided root-bound continuation cursor; Android never manufactures or widens the immutable server head;
- a successful response with a different root fails closed before visible state can be composed;
- HTTP **410** becomes a distinct refresh-required result and is never silently retried against the new current root;
- client recreation between pages does not change correctness because retained root identity and opaque server cursors carry the continuation state.

Android also validates the complete server cursor envelope before reuse. The outer root id, inner resource schema, campaign identity or list-status filter, position/total/last-campaign binding and hash/digest format must satisfy the same fail-closed invariants as the server-side cursor types. A cursor for another root, campaign, resource type or filter is rejected locally rather than being reinterpreted.

The A4-24 overlap checks remain defence-in-depth. Even when every response carries the same root, Android rejects contradictory campaign/timeline counts or hashes and contradictory evidence verification/head values.

A4-25e race qualification covers response-root changes, retained-root continuation after client recreation, expired roots, malformed/mismatched cursor envelopes and server-owned continuation semantics. This is repository/unit-contract qualification only; no physical acceptance is inferred.

## No server-side session

`snapshot_id` is a content-addressed immutable manifest identity, not an in-memory paging session. Restart does not change the meaning of a retained snapshot id.

The server may keep an in-memory cache of verified immutable manifests as an optimization only. Cache loss must not change correctness.

## Retention

The first implementation uses a hard bounded retention policy:

- retain at most the newest **256** root snapshots;
- a root snapshot may additionally expire after **15 minutes**;
- once either bound evicts a root, requests using its id fail closed with HTTP **410** from the dormant v2 adapter and the client must refresh;
- garbage collection may delete a campaign snapshot blob only when no retained root manifest references it;
- garbage collection is never part of the commit point.

The snapshot-unavailable response is distinguishable from success, 404 resources and malformed requests, and is never converted into offset/local continuation behaviour.

## Production activation guard

Even with A4-25a-e repository-qualified, the production operator mount **must not mount `Agent4RuntimeContext`** or switch to the dormant v2 snapshot path without a separate explicit production-wiring decision and qualification.

`Agent4RuntimeContext` contains lifecycle mutation authority and live operator services over mutable stores. The current production mount continues to accept only the narrow `Agent4OperatorReadContext` used by A4-21.

Tests that need a full dormant runtime must exercise its operator services directly or build the transport router explicitly; they must not use the production mount as a shortcut.

This guard is intentionally stronger than relying on the current entrypoint to "usually" pass a read-only context. Repository qualification proves the snapshot authority and consumer contracts; it does not itself authorize concurrent writer + read activation.

## Planned implementation sequence

### A4-25a — decision + guard

- this document;
- production mount rejects full writer runtime;
- adversarial repository contracts prove the guard;
- no physical candidate churn.

**Stacked status:** implemented and exact-head qualified in PR #459.

### A4-25b — immutable snapshot domain/store

- typed campaign snapshot and root manifest schemas;
- content-addressed ids;
- append-only durable storage;
- atomic/fail-closed current pointer;
- crash-window tests for every publication step;
- bounded retention and reference-safe GC.

**Stacked status:** implemented and exact-head qualified in PR #465.

### A4-25c — writer publication

- one snapshot publisher owned by the full runtime;
- publish only after required projection reconciliation/evidence commit;
- pending projection rejection;
- deterministic restart/recovery tests.

**Stacked status:** implemented and exact-head qualified in draft PR #468; qualified parent lineage is retained by the later A4-25 slices.

### A4-25d — snapshot-bound operator API

- operator services read only immutable snapshots in concurrent mode;
- `snapshot_id` on list/detail/timeline/evidence/verification responses;
- all continuations bind to it;
- stale/expired ids fail closed;
- backend remains a transparent authenticated proxy.

**Stacked status:** implemented and exact-head qualified as a dormant v2 server slice in draft PR #470. This qualification does not authorize production wiring.

### A4-25e — Android and race qualification

- Android carries one server snapshot id across each logical detail/list flow;
- response root mismatch fails closed;
- timeline/evidence continuation cannot widen server heads;
- root-bound cursor envelopes mirror server cursor invariants;
- expired roots require explicit refresh rather than silent fallback;
- client recreation between pages preserves deterministic retained-root continuation;
- A4-24 overlap checks remain active as defence-in-depth.

**Stacked status:** implemented and exact-head qualified as a dormant Android v2/race slice in draft PR #473. Qualification is repository/unit-contract evidence only; physical acceptance and production wiring remain separate.

## Explicit non-goals of A4-25a

The original A4-25a guard slice deliberately made none of the runtime changes later implemented on stacked A4-25b/c/d/e branches:

- no snapshot files were written by A4-25a;
- no API schema changes were made by A4-25a;
- no Android changes were made by A4-25a;
- no lifecycle activation;
- no background publisher or GC loop;
- no merge to `main` during the 1.58.151 freeze;
- no modification or invalidation of the independently qualified A4-18 physical chain.

Those historical A4-25a boundaries do not authorize production activation. `production_activation=false` remains mandatory.
