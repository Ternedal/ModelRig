# Asymmetric authority and publisher authorization v2

Hardening H5 introduces a verification-first asymmetric authority boundary. It
remains an offline evidence mechanism. It does not add a Git remote, GitHub
credential, network write, branch push, pull-request mutation, reviewer request,
ready-for-review conversion, merge, release, settings change, deployment or tool
activation.

## H5A — verification-only Ed25519 authority

`kaliv_dev_control.asymmetric_authority` contains only:

- pinned Ed25519 public-key identities;
- issuer actor and issuer system identities;
- validity intervals;
- monotonically increasing keyring epochs;
- explicit revocation state;
- the fixed key-custody policy identity;
- canonical detached-signature evidence; and
- public-key verification.

The runtime module deliberately has no private-key type, signer implementation,
private-key loader, credential adapter, transport or remote-write capability.
Private signing material must remain outside the repository, worker, Development
Control Plane process, staged runtime and generated evidence.

The exact signing message is domain-separated and binds:

1. key ID;
2. issuer actor;
3. issuer system;
4. keyring epoch;
5. key-custody-policy SHA-256; and
6. the exact canonical payload bytes.

Verification fails closed for an unknown key, actor/system mismatch, unsupported
custody policy, stale keyring epoch, signature time outside the key validity
window, future signature, revoked key, payload mismatch or invalid Ed25519
signature. Revocation applies at verification time even when the signature was
created before the revocation timestamp.

`cryptography==50.0.0` is pinned in both the Development Control Plane package
metadata and the repository test/runtime requirements. The implementation uses
the library's official Ed25519 public-key primitive; no custom cryptography is
implemented.

## H5B — publisher authorization lease v2

`kaliv-development-publisher-authorization-lease/v2` replaces the embedded HMAC
field with one complete detached Ed25519 signature artifact. The unsigned lease
payload still binds the exact signed publisher request, task, readiness,
invocation nonce, repository identity, credential policy, authorization policy,
issue time, expiry time and human-only merge boundary.

`build_asymmetric_publisher_authorization_payload(...)` produces only the exact
canonical unsigned bytes for transfer to an external signing boundary. It does
not accept a secret, private key, token, credential, GitHub client or transport.

An external signer must return a detached signature that agrees with the lease
on:

- issuer key ID;
- issuer actor;
- issuer system;
- issue/signature timestamp;
- keyring epoch;
- custody-policy identity; and
- payload SHA-256.

`AsymmetricPublisherAuthorizationVerifier` then verifies the detached signature
using an `Ed25519AuthorityVerifier` containing public keys and revocation state
only. It independently re-verifies the publisher request, task, semantic review,
current control-plane authority and lease time window.

Tests use an ephemeral Ed25519 private key only inside the test module. They prove
valid verification, canonical round-trip and schema parity, plus failure on
payload tampering, wrong public key, revocation, keyring rollback, lease/signature
identity mismatch and expiry.

## Compatibility state

The original v1 HMAC authorization implementation remains temporarily available
as internal compatibility code because replay, preflight, postcondition and local
candidate tests still exercise the original artifact family. It is not removed or
silently treated as asymmetric authority.

Therefore H5A and H5B establish the new production-oriented verification and
lease format, but they do **not** yet claim complete migration of all downstream
artifacts. The next migration must:

1. version replay, preflight and postcondition artifacts for the v2 lease;
2. move local candidate materialization to those v2 artifacts;
3. make the public publisher-authorization facade reject new v1 issuance; and
4. physically remove the retained HMAC issuer and shared-secret verifier path
   after all fixtures have migrated.

Until that migration is complete, no production signing or publisher authority
is claimed.
