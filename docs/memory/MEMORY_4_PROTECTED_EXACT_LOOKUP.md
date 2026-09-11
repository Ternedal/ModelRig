# Memory 4.0 — protected verbatim exact-match sidecar

Status: default-off storage scalability slice for Memory 4.0 W02-B. This design is
local-only and does not activate normal-chat writes, Agent 3, cloud memory or
production behavior.

## Problem

W02-A treats distinct canonical `user/verbatim_user_statement` values as
independent log entries. Legacy/plaintext W02-B can therefore narrow a fresh
snapshot by exact `value` before replanning.

Protected memory intentionally stores `value=''` in SQLite and keeps the real
value only in the protected envelope. Without another lookup primitive, protected
W02-B must select and decrypt the whole canonical subject/predicate slot. That is
correct and fail-closed, but its existing 128-row hard bound eventually becomes an
availability limit for long protected verbatim history.

The goal of this sidecar is exact-match selection without plaintext indexes and
without turning a digest into memory authority.

## Threat and authority model

The sidecar is designed to prevent a copied SQLite database from cheaply exposing
verbatim values or equality through an unkeyed digest.

It does **not** make SQLite itself an authenticated database. The existing memory
database, schema and lifecycle rows remain part of the trusted local storage
boundary. Corruption or unsupported mutation that makes the sidecar observably
incomplete fails closed, but this slice does not claim cryptographic detection of
every possible malicious SQLite rewrite.

The sidecar never grants fact, review, correction or supersede authority. A match
is only a bounded selector. Every selected memory row is still opened through the
protected reader and the ordinary W02-A planner is rerun while W02-B holds its
write transaction.

No model output or caller input can provide a digest, lookup key, sidecar memory
id or sidecar mutation operation.

## Per-store keyed blind index

`ProtectedMemoryVerbatimLookupMigrator` creates the explicit optional sidecar for
active, private, protected canonical verbatim rows whose review state is
`pending` or `confirmed`.

The migration generates one random 256-bit per-store HMAC key. The key is stored
only as ciphertext produced by the already selected local protection provider,
with a domain-separated entropy value bound to sidecar schema/provider/key scope.
SQLite never stores the raw lookup key.

For each eligible canonical value, the sidecar stores a domain-separated
HMAC-SHA256 fingerprint. It does not store:

- verbatim plaintext;
- `source_ref` plaintext;
- an unkeyed SHA-256 of the value;
- deterministic protected value ciphertext;
- a caller- or model-supplied fingerprint.

The key is generated independently per store, so equal verbatim values in two
stores do not intentionally expose cross-store equality through the sidecar.

## Explicit resumable migration and repair

The sidecar is not created at worker startup and is not required by the existing
protected reader/writer or the landed non-indexed W02-B path.

Migration requires the base protected-memory migration to be complete and enters
an explicit offline/exclusive SQLite migration mode. It first prunes stale sidecar
rows, then indexes missing eligible rows. Both operations are bounded by
`batch_limit` and commit incrementally, so a large repair can resume after a
partial run without rotating the already protected per-store key.

The migration receipt remains `running` until stale-row count and missing-row
count both reach zero. Only then is it marked `completed`.

Re-running the migrator is the explicit repair operation after an out-of-band
protected create/correction/delete/supersede has made the sidecar stale or
incomplete.

No unbounded decrypt scan is used at runtime to prove exact-value absence. The
explicit offline migration/repair is the operation allowed to walk historical
protected rows.

## Lifecycle-minimal sidecar

The sidecar represents exactly the eligible active canonical set, not historical
superseded/deleted versions.

Runtime completeness validation compares:

- the number of eligible active protected canonical rows;
- total sidecar row count;
- the qualifying memory/index join count;
- sidecar schema and fixed-size lowercase-hex fingerprint shape.

Missing index rows, stale extra rows or malformed fingerprints fail closed before
indexed W02-B memory mutation.

This is deliberately stricter than keeping fingerprints forever: a completed
sidecar must not retain a content-derived fingerprint for a row that has become
non-active.

## Indexed W02-B composition

`apply_protected_consolidation_plan_indexed(...)` is an explicit opt-in protected
W02-B entry point for a store whose sidecar migration is complete.

It does **not** silently create or repair a sidecar. If the sidecar is absent,
running, stale or incomplete, this indexed entry point fails closed. Callers that
have not opted into #1216 continue to use the already landed
`apply_protected_consolidation_plan(...)` path, which retains its bounded
fail-closed behavior.

For structured candidates, indexed W02-B preserves the existing bounded exact
subject/predicate lookup.

For canonical verbatim candidates:

1. compute the server-side HMAC selector from the candidate value;
2. query only matching sidecar fingerprints within W02's existing-row bound;
3. open every selected row with `ProtectedMemoryReader` using exact
   `LOCAL_MANAGEMENT` authority;
4. require the decrypted value to correspond to the selected fingerprint;
5. rerun the unchanged `MemoryConsolidator` against those durable records;
6. require the fresh plan to match the supplied W02-A plan, except for the landed
   exact replay rule;
7. apply the ordinary protected W02-B mutation;
8. maintain the lifecycle-minimal sidecar inside the same transaction.

A canonical verbatim `existing_id` carried by the input plan is deliberately not
used as a fallback selector. Canonical dedupe/supersede targets must be
rediscovered through the keyed selector and then decrypted. Otherwise a stale or
forged plan could bypass the exact-match sidecar.

## Atomic write-side maintenance

Sidecar maintenance shares the protected W02-B transaction.

A newly created eligible canonical row is indexed before commit. During the one
permitted exact pending-to-confirmed verbatim promotion, the new active version is
indexed and the newly superseded predecessor is removed from the sidecar before
the transaction commits.

If encryption, memory insert/versioning, sidecar insert/remove, final completeness
validation or any later write step fails, the outer transaction rolls back both
memory and sidecar changes.

Ordinary `ProtectedMemoryWriter` calls do not silently gain sidecar authority. If
such an out-of-band write changes the eligible canonical set, the next indexed
W02-B call detects the mismatch and fails closed until the explicit migrator is
run again.

## Privacy and leakage expectations

Qualification checks that sampled protected verbatim values and source refs do
not reappear in SQLite-family plaintext and that stored fingerprints are not equal
to plain `SHA256(value)`.

The sidecar necessarily exposes local metadata such as eligible row cardinality
and the existence of opaque fixed-size fingerprints. That is an accepted local
storage tradeoff for bounded equality lookup. The HMAC key remains protected by
the same local current-user provider boundary as protected memory.

## Qualification focus

The focused qualification covers:

- more than 128 protected canonical history rows;
- resumable bounded migration/repair;
- indexed create, exact dedupe and replay;
- exact pending-to-confirmed version promotion;
- stale/missing sidecar fail-closed behavior;
- out-of-band ordinary writer invalidation;
- atomic rollback of memory and sidecar state on late failure;
- lifecycle cleanup of superseded predecessor fingerprints;
- per-store lookup-key separation;
- sampled plaintext/source-ref absence;
- rejection of unkeyed-hash equivalence;
- selector tampering that cannot be bypassed by a plan-supplied canonical
  `existing_id`.

## Non-goals

This slice adds no:

- normal `/api/v1/chat` persistence hook;
- background consolidation scheduler;
- public HTTP write or lookup route;
- Agent 3 activation dependency;
- cloud/private-cloud grant;
- model/embedding/network lookup;
- delete authority;
- semantic stale-fact replacement;
- production activation.

`production_activation=false`
