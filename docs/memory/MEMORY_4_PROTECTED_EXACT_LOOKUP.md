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

No model output or caller input can provide a digest, lookup key, memory id for a
sidecar row, or sidecar mutation operation.

## Per-store keyed blind index

`ProtectedMemoryExactLookupMigrator` creates an optional sidecar for active,
private canonical verbatim rows.

The migration generates a random 256-bit per-store HMAC key. The key is encoded
inside an envelope using the existing `MemoryProtectionCodec` and current
protection provider/key scope. SQLite never stores the raw key.

For each qualifying canonical value, the sidecar stores a domain-separated
HMAC-SHA256 digest. It does not store:

- verbatim plaintext;
- `source_ref` plaintext;
- an unkeyed SHA-256 of the value;
- deterministic protected value ciphertext;
- a caller- or model-supplied fingerprint.

Separate stores receive separate random HMAC keys, so equal verbatim values in
two stores do not intentionally expose cross-store equality through the sidecar.

## Explicit migration and rebuild

The sidecar is not created at worker startup and is not required by the existing
protected reader/writer.

Migration first validates the existing protected-memory boundary, then rebuilds
the sidecar atomically under a SQLite write transaction. Existing protected
values are decrypted only for this explicit local rebuild. If migration fails,
the prior committed sidecar remains authoritative; a partial rebuilt index is not
published.

Re-running migration is the repair operation after an out-of-band protected write
has made the sidecar incomplete. The rebuild reuses the already protected
per-store lookup key rather than exposing or rotating it implicitly.

No unbounded decrypt scan is used at runtime to prove absence. The explicit
migration/rebuild is the operation that may walk historical protected rows.

## Runtime completeness

A completed sidecar records its schema, provider, key scope, revision and indexed
row count. Before an indexed exact lookup is trusted, runtime validation compares:

- the number of currently qualifying active canonical memory rows;
- total sidecar row count;
- qualifying memory/index join count;
- recorded indexed-row count;
- sidecar digest/revision shape.

If these do not agree, indexed lookup fails closed before memory mutation.

This catches normal unsupported/out-of-band lifecycle changes such as an ordinary
protected create, correction or delete that did not maintain the sidecar. The
operator must explicitly rebuild the sidecar before using indexed W02-B again.

## Indexed W02-B composition

`apply_indexed_protected_consolidation_plan(...)` is an opt-in composition around
the landed W02-B writer.

For structured candidates, it preserves the existing bounded exact
subject/predicate lookup.

For canonical verbatim candidates when the sidecar is installed:

1. compute the server-side HMAC selector from the candidate value;
2. query only matching sidecar ids within W02's existing-row bound;
3. open every selected row with `ProtectedMemoryReader` using exact
   `LOCAL_MANAGEMENT` authority;
4. rerun the unchanged `MemoryConsolidator` against those durable records;
5. require the fresh plan to match the supplied W02-A plan, except for the already
   proven exact replay rule;
6. apply the ordinary protected W02-B mutation;
7. update create/supersede sidecar rows inside the same transaction.

A canonical verbatim `existing_id` carried by the input plan is deliberately not
used as a fallback selector once the sidecar is installed. Dedupe/supersede
targets must be rediscovered by the keyed selector and then decrypted. Otherwise
a stale or forged plan could bypass the exact-match sidecar.

If the sidecar has never been installed, the indexed composition preserves the
landed protected W02-B behavior: it uses the bounded canonical slot scan and can
fail closed once the relevant protected history exceeds the existing hard bound.

## Atomicity

Sidecar maintenance shares the protected W02-B transaction.

A newly created canonical row is indexed before commit. During the one permitted
exact pending-to-confirmed verbatim promotion, the new active version is indexed
and the superseded predecessor is removed from the active sidecar.

If encryption, memory insert/versioning, sidecar update or validation fails late,
the outer transaction rolls back both memory and sidecar changes.

## Privacy and leakage expectations

Qualification verifies that sampled protected verbatim values and source refs do
not reappear in SQLite-family plaintext and that stored fingerprints differ from
plain SHA-256(value).

The sidecar necessarily exposes local metadata such as row cardinality and the
existence of opaque fixed-size fingerprints. That is an accepted local storage
tradeoff for bounded equality lookup. The HMAC key remains protected by the same
local current-user provider as the memory boundary.

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
