# H6 — authenticated publisher replay recovery

H6 makes dual Ed25519 authorization mandatory for the **supported public** publisher-replay recovery path.

It does not add a Git remote, GitHub credential, network client, branch push, pull-request mutation, reviewer request, ready-for-review conversion, merge, release, settings change, deployment or production authority.

## Problem closed by H6

The retained H5C ledger recovery implementation required a caller-supplied authorization hash and operator actor ID, but the supported runtime did not independently verify that those values represented a real approval.

H6 introduces a new public ledger boundary, `PublisherReplayLedgerV3`, and maps the existing public compatibility name `PublisherReplayLedgerV2` to that class. Its inherited raw `recover()` method always fails closed. Recovery is available only through `recover_authenticated()`.

## Exact durable-state snapshot

`kaliv-development-publisher-replay-recovery-state/v1` binds:

- the exact Ed25519 authorization lease hash;
- invocation nonce;
- replay-ledger ID;
- canonical observation timestamp;
- classified durable state;
- presence and SHA-256 of the final replay entry;
- presence and SHA-256 of the pending replay entry;
- presence and SHA-256 of the reservation file; and
- presence and SHA-256 of an existing recovery receipt.

Every observed path must be a regular, link-free, bounded file. The snapshot therefore binds the bytes that justify the requested recovery action rather than trusting a state-name string alone.

Immediately before mutation, `recover_authenticated()` re-observes and rehashes the same paths. Any presence, byte, hash, lease, nonce, ledger or state change invalidates the authorization before it is durably published.

## Recovery authorization

`kaliv-development-publisher-replay-recovery-authorization/v1` contains:

- the complete durable-state snapshot and hash;
- exactly one action: `finalize_prepared`, `acknowledge_committed`, or `tombstone_uncertain`;
- request and expiry timestamps;
- operator actor, system and key identities;
- independent reviewer actor, system and key identities;
- recovery-policy and asymmetric-key-custody-policy hashes;
- detached operator Ed25519 evidence;
- detached reviewer Ed25519 evidence; and
- `nonce_reusable: false`.

The unsigned payload builder accepts no private key, signer, secret, credential, token, client or transport. Signing is performed outside the runtime boundary.

## Independent authority

Operator and reviewer must differ by actor, system and key ID. Both signatures cover the same canonical payload.

At verification time neither recovery actor may equal any prior authority role transitively embedded by the lease:

- developer;
- semantic reviewer;
- publisher; or
- publisher-authorization issuer.

Each signature is checked through its own `Ed25519AuthorityVerifier`, including pinned public key, issuer identity, keyring epoch, validity window, custody-policy identity and revocation state.

## Time and action constraints

An authorization lasts at most ten minutes. The durable-state observation must be no later than the request time, and recovery must occur at or after the request but strictly before expiry.

Actions are state-specific:

- `finalize_prepared` requires `prepared`;
- `acknowledge_committed` requires `committed` or `committed_locked`; and
- `tombstone_uncertain` requires `reserved` or `partial`.

A mismatched action cannot be signed through the canonical payload builder.

## Durable execution boundary

Before invoking the retained, already-tested H5C mutation core, H6 publishes the exact authorization create-once as:

```text
<invocation-nonce>.v2.recovery-authorization.json
```

The H5C recovery receipt stores the SHA-256 of that complete authorization. If the authorization file already exists, only byte-identical evidence is accepted.

If the process crashes after authorization publication but before mutation, the identical authorization may be retried against the unchanged durable state. A different authorization conflicts fail closed. If state changed, the signed snapshot no longer verifies.

## Irreversibility

Recovery never makes a nonce reusable. Uncertain state can only become a permanent tombstone. After successful recovery, replaying the same authorization fails because the current durable-state snapshot differs from the signed snapshot.

The replay-ledger directory remains an external trusted operating boundary. H6 does not claim distributed consensus, protection against a separate administrator or kernel component, or proof that a biological human personally operated either signing key.

## Schemas

- `schemas/development-publisher-replay-recovery-state-v1.schema.json`
- `schemas/development-publisher-replay-recovery-authorization-v1.schema.json`
- retained output: `schemas/development-publisher-replay-recovery-receipt-v2.schema.json`

## Adversarial proof

`tests/test_publisher_recovery_authorization_h6.py` proves:

- raw public recovery is disabled;
- the public compatibility name resolves to the H6 ledger;
- both signatures are required and verified independently;
- actor overlap with prior authority roles fails closed;
- expired authorization fails closed;
- wrong reviewer signatures fail closed;
- action/state mismatches cannot be built;
- durable file drift fails before authorization publication;
- successful tombstone recovery durably binds the complete authorization;
- a recovered nonce remains permanently non-reusable;
- schema fields match canonical artifacts;
- authorization storage is canonical and create-once; and
- the runtime module contains no private-key, HMAC, credential, network or GitHub-write surface.
