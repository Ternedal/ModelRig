# Physically primary publisher recovery ledger (H9)

H9 removes H7's import-time mutation of recovery classes. The supported public
ledger and verifier now have one ordinary, physically defined implementation in
`kaliv_dev_control.publisher_recovery_primary`.

The change preserves every canonical H6–H8 artifact and transition. It adds no
credential, token, private-key loader, Git remote, Git transport, network
client, GitHub writer, pull-request mutation, reviewer request,
ready-for-review conversion, merge, release, settings or deployment authority.

## Previous import-time behavior

H7 originally retained the H6 ledger class object and modified it while
`publisher_recovery_receipt_v3` was imported:

- the recovery verifier reference in another module was replaced;
- `PublisherReplayLedgerV3.recover_authenticated` was reassigned; and
- a class marker recorded that the replacement had been installed.

The runtime behavior was tested, but class authority depended on import order
and receipt-artifact import side effects.

## H9 physical structure

H9 separates three responsibilities:

1. `publisher_recovery_authorization` remains the retained H6 authorization and
   fail-closed durable transition core.
2. `publisher_recovery_receipt_v3` is passive artifact code only: receipt model,
   canonical parser and durable create-once writer.
3. `publisher_recovery_primary` contains the single supported verifier and the
   public ledger method that invokes the H6 transition core and then publishes
   canonical receipt v3.

The public `PublisherReplayLedgerV2` compatibility name and
`PublisherReplayLedgerV3` both resolve to the physical H9 ledger class. The
strict-verifier compatibility module and the H8 finalizer resolve to the same
physical verifier and ledger.

## Preserved durable order

The exact durable order remains:

1. observe and hash the exact replay state;
2. verify independent operator and reviewer Ed25519 signatures;
3. verify both detached signature timestamps inside the approval window;
4. durably publish the complete recovery authorization;
5. execute the retained H6/H4 fail-closed v2 transition;
6. construct receipt v3 from the exact authorization and v2 receipt;
7. durably create the missing receipt-v3 file; and
8. reload it canonically and compare the exact content.

A crash after step 5 and before step 7 remains the explicit H8 finalizer case.
H9 does not hide, retry or reinterpret that boundary.

## Compatibility and non-expansion

H9 does not change:

- authorization, state, ledger-entry, v2-receipt or v3-receipt schemas;
- canonical JSON or SHA-256 calculations;
- allowed recovery actions or state transitions;
- the rule that a consumed or uncertain nonce is never reusable;
- the dual-signature identity-separation policy;
- H8's receipt-only finalization contract; or
- the absence of remote publication and GitHub-write authority.

The retained H6 classes remain available as internal base implementations, but
importing receipt-v3 code no longer mutates them.

## Verification coverage

H9 tests require:

- one public physical ledger class under both compatibility names;
- one public verifier shared by the strict compatibility import and finalizer;
- an explicit `recover_authenticated` method on the physical ledger;
- inheritance from, rather than mutation of, the retained H6 core;
- no H7 installation marker or method reassignment;
- a passive receipt-v3 module with no verifier or ledger authority; and
- no signer, credential, transport, GitHub, merge, release or deployment
  surface in the primary implementation.

The existing H7 and H8 end-to-end matrices continue to prove all three recovery
transitions, canonical receipt bytes, tamper rejection and missing-receipt
finalization.
