# Agent 4 A4-25 — server-side snapshot authority

Status: **design decision + activation guard; runtime implementation deliberately deferred**.

Issue: #458.

This slice does not change the qualified A4-18 physical candidate and does not enable lifecycle orchestration. It records the consistency model required before any future production composition may expose Agent 4 lifecycle mutation and operator reads concurrently.

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

## No server-side session

`snapshot_id` is a content-addressed immutable manifest identity, not an in-memory paging session. Restart does not change the meaning of a retained snapshot id.

The server may keep an in-memory cache of verified immutable manifests as an optimization only. Cache loss must not change correctness.

## Retention

The first implementation must use a hard bounded retention policy:

- retain at most the newest **256** root snapshots;
- a root snapshot may additionally expire after **15 minutes**;
- once either bound evicts a root, requests using its id fail closed with an explicit stale/expired-snapshot response and the client must refresh;
- garbage collection may delete a campaign snapshot blob only when no retained root manifest references it;
- garbage collection is never part of the commit point.

The exact API status/detail is decided with the wire-contract implementation, but it must be distinguishable from success and must never be converted into offset/local continuation behaviour.

## Production activation guard

Until the immutable snapshot authority above is implemented and wired into the operator API, the production operator mount **must not mount `Agent4RuntimeContext`**.

`Agent4RuntimeContext` contains lifecycle mutation authority and live operator services over mutable stores. The production mount may accept only the narrow `Agent4OperatorReadContext` used by A4-21.

Tests that need a full dormant runtime must exercise its operator services directly or build the transport router explicitly; they must not use the production mount as a shortcut.

This guard is intentionally stronger than relying on the current entrypoint to "usually" pass a read-only context. It makes concurrent writer + read activation an explicit future code change that must first implement this decision.

## Planned implementation sequence

### A4-25a — decision + guard

- this document;
- production mount rejects full writer runtime;
- adversarial repository contracts prove the guard;
- no physical candidate churn.

### A4-25b — immutable snapshot domain/store

- typed campaign snapshot and root manifest schemas;
- content-addressed ids;
- append-only durable storage;
- atomic/fail-closed current pointer;
- crash-window tests for every publication step;
- bounded retention and reference-safe GC.

### A4-25c — writer publication

- one snapshot publisher owned by the full runtime;
- publish only after required projection reconciliation/evidence commit;
- pending projection rejection;
- deterministic restart/recovery tests.

### A4-25d — snapshot-bound operator API

- operator services read only immutable snapshots in concurrent mode;
- `snapshot_id` on list/detail/timeline/evidence/verification responses;
- all continuations bind to it;
- stale/expired ids fail closed;
- backend remains a transparent authenticated proxy.

### A4-25e — Android and race qualification

- Android carries one server snapshot id across each logical detail/list flow;
- transition a campaign between every pair of related reads;
- mutate evidence between every pair of related reads;
- prove no mixed successful view;
- restart writer/reader between pages and verify deterministic retained/expired behaviour;
- exact-head CI and later physical validation before concurrent activation.

## Explicit non-goals of A4-25a

- no new snapshot files are written yet;
- no API schema changes;
- no Android changes;
- no lifecycle activation;
- no background publisher or GC loop;
- no merge to `main` during the 1.58.151 freeze;
- no modification or invalidation of A4-18 physical head `e19833097d107f6ca69c1e23bb2f035fc15e1b4d`.

`production_activation=false` remains mandatory.
