# Publisher recovery receipt v3 (H7)

H7 consolidates the supported publisher replay recovery verifier and binds the
complete authenticated recovery authorization into one canonical recovery
receipt.

The change remains dormant and local-only. It adds no credential, token, Git
remote, Git transport, network client, GitHub writer, pull-request mutation,
review request, ready-for-review conversion, merge, release, settings or
deployment authority.

## Single supported verifier

The supported `PublisherReplayRecoveryAuthorizationVerifierV1` performs all H6
checks in one class:

- exact canonical durable-state equality;
- exact lease, invocation nonce and ledger binding;
- recovery and custody policy binding;
- short authorization lifetime;
- verification inside the authorization window;
- operator and reviewer Ed25519 verification;
- operator/reviewer independence;
- separation from developer, semantic reviewer, publisher and lease issuer; and
- both detached signature timestamps inside the exact approval window.

The former `publisher_recovery_authorization_strict` module is now only a
compatibility re-export of this class. It contains no second verifier
implementation.

## Receipt v3

`kaliv-development-publisher-replay-recovery-receipt/v3` embeds:

- the complete canonical H6 authorization;
- the authorization SHA-256;
- the exact durable v2 transition receipt;
- the v2 receipt SHA-256;
- lease, nonce and ledger identities;
- recovery time and action;
- state before and after;
- entry-verification outcome;
- `authorization_embedded: true`; and
- `nonce_reusable: false`.

The constructor rejects any mismatch between the embedded authorization, its
signed durable state, the retained v2 transition evidence and the receipt-v3
summary fields.

## Supported transitions

The exact allowed transitions are:

| Authorized action | Signed state before | Durable state after | Entry verified |
| --- | --- | --- | --- |
| `finalize_prepared` | `prepared` | `committed` | `true` |
| `acknowledge_committed` | `committed` or `committed_locked` | `committed` | `true` |
| `tombstone_uncertain` | `reserved` or `partial` | `tombstoned` | `false` |

No transition makes an invocation nonce reusable.

## Durable order

The retained H6/H4 ordering is preserved:

1. observe and hash the exact durable state;
2. verify both Ed25519 signatures;
3. durably publish the complete authorization;
4. execute the retained fail-closed v2 recovery transition;
5. durably publish receipt v3 containing the authorization and v2 receipt;
6. reload receipt v3 canonically and compare it byte-for-byte.

The v2 receipt remains an internal transition record. Receipt v3 is the
complete authenticated evidence intended for supported consumers.

## Honest crash boundary

Receipt v3 is written after the durable v2 transition because it must report an
observed completed transition rather than claim future work.

A process or storage failure between steps 4 and 5 can therefore leave:

- the complete durable authorization;
- the completed/tombstoned v2 transition evidence; and
- no receipt v3.

That state does not become success and does not make the nonce reusable. It is
fail-closed evidence requiring an explicit, separately designed receipt
finalization procedure before a consumer may rely on receipt v3.

H7 intentionally does not invent such a procedure implicitly. A future slice
may add a narrowly scoped, authenticated finalizer bound to the existing
authorization and v2 receipt.

## Verification coverage

H7 tests construct and execute all three durable transitions end-to-end. Each
test:

- creates the exact durable before-state;
- observes and hashes that state;
- signs one canonical authorization with independent operator and reviewer
  Ed25519 keys;
- executes authenticated recovery through the public ledger;
- verifies the resulting state and receipt fields;
- reloads receipt v3 from disk; and
- requires byte-canonical equality.

Additional tests reject field tampering, duplicate output, schema drift and any
new signer, shared-secret or transport surface.
