# Publisher recovery receipt v3 finalizer — H8

H8 closes one narrow evidence-publication gap left by H7.

A valid authenticated recovery can complete its durable v2 transition and then
lose the process before the deterministic receipt v3 is published. In that
state the nonce is already committed or permanently tombstoned, the exact
recovery authorization and v2 receipt are durable, and the receipt v3 is
missing.

H8 can publish only that missing receipt. It cannot repeat or alter recovery.

## Public operation

```python
finalize_missing_publisher_replay_recovery_receipt_v3(
    ledger=ledger,
    lease=lease,
    authorization_verifier=verifier,
    finalized_at_utc=timestamp,
)
```

The caller cannot supply an authorization object, v2 receipt, action, state,
output path or receipt body. The finalizer derives every path from the exact
lease nonce and ledger root and loads canonical durable evidence from:

```text
<nonce>.v2.recovery-authorization.json
<nonce>.v2.recovery.json
```

It will create only:

```text
<nonce>.v3.recovery.json
```

An existing v3 file, including a symlink, fails closed rather than becoming an
idempotent replay surface.

## Required verification

Before publication H8 requires all of the following:

1. the exact H7 ledger, asymmetric lease and consolidated Ed25519 verifier;
2. canonical, link-free durable authorization and v2 receipt files;
3. exact lease hash, nonce and ledger identity across every artifact;
4. the v2 receipt authorization hash to equal the complete authorization hash;
5. both independent Ed25519 signatures to verify at the recorded recovery time;
6. the original authorization and signature times to be valid for that recovery;
7. finalization time not to predate the completed transition;
8. the current ledger state to equal the recorded durable post-state;
9. the v2 recovery file hash to equal the embedded core-receipt hash;
10. no pending entry or reservation to remain;
11. the committed final entry to equal the exact signed pre-state entry for
    `finalize_prepared` or `acknowledge_committed`; and
12. no final entry to exist for `tombstone_uncertain`.

The finalizer may run after the original recovery authorization has expired.
That authorization governed the already completed state transition, not the
later deterministic evidence publication. Its signatures are therefore checked
at `core_receipt.recovered_at_utc`, while the finalization timestamp is required
only to be at or after that transition.

## Deterministic output

H8 constructs `PublisherReplayRecoveryReceiptV3` through the same H7
`from_core()` path. It adds no finalizer-specific timestamp, actor or authority
claim. The resulting canonical bytes are exactly the bytes H7 would have
published immediately after the transition.

The v3 file is written through the existing durable create-once primitive,
loaded again canonically and compared byte-for-byte. Durable nonce state is
observed immediately before and after publication; every tracked field and hash
must remain identical.

## Fail-closed behavior

H8 refuses finalization when:

- either durable evidence file is missing, non-canonical, replaced or tampered;
- identities or hashes do not form one exact authority chain;
- signature verification fails;
- the finalization timestamp predates recovery;
- state has drifted, cleanup is incomplete or the final entry differs;
- receipt v3 already exists; or
- durable create-once publication or canonical reload cannot be proven.

Failure never invokes recovery, removes files, changes a replay entry, cleans a
reservation, converts state or makes a nonce reusable.

## Capability boundary

H8 contains no private-key loader, signer, shared secret, credential, token,
subprocess, Git command, remote, socket, HTTP client, GitHub writer,
pull-request mutation, reviewer request, ready-for-review, merge, release,
settings, deployment or production authority.

The only mutation is create-once publication of the exact missing local receipt
v3 after the recovery transition has already completed and been independently
verified.
