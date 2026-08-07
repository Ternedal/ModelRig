# DC-L04 preflight — signed physical Windows evidence contract

**Status:** draft candidate; exact-head validation and independent review pending  
**Base:** `main @ b717055790947ea848418964e7ebd78c39c39ee3`  
**Source:** PR #338 @ `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Depends on:** landed DC-L02 and DC-L03

## Purpose

DC-L04 lands the canonical physical Windows-isolation evidence model, detached
operator signature, durable create-once evidence publication and local operator
sign/verify CLI. It defines evidence; it does not create Windows containment.

## Included authority

- eleven fixed probe identities;
- exact task, repository, base, catalog, toolchain, rig, workspace and authority
  binding;
- separate collector and approver identities;
- canonical JSON and SHA-256 identities;
- detached HMAC-SHA256 using an operator-controlled key;
- exactly one fresh matching signed report;
- local bounded evidence/key loading; and
- crash-durable no-replace publication.

## Explicit exclusions

- no DC-L05 Windows Job Object, AppContainer, ACL or process-launch substrate;
- no non-empty catalog execution authority;
- no GitHub write, remote Git, credential loader, push or PR mutation;
- no reviewer request, ready-for-review, merge, release, deployment or activation;
- no claim that hosted CI is physical I0b evidence; and
- no reuse of evidence created before the final authority freeze.

## Required projections from source

1. Remove the obsolete positive catalog-materialization assertion. DC-L03 now keeps
   every non-empty catalog fail-closed.
2. Preserve the original operator path before symlink checks; CLI code must not
   resolve away a symlink supplied by the operator.
3. Harden evidence, attestation and key reads with finite bounds and stable regular
   file identity.
4. Snapshot the isolation attestation before verification.
5. Keep package exports and CLI limited to already-landed dependencies.

## Merge gates

- changed paths exactly equal `exact-path-allowlist.json`;
- source provenance and symbol ownership agree with the final diff;
- portable DevControl discovery and workflow coverage pass;
- all repository workflows pass on the exact head;
- load-bearing mutations have demonstrated red/green behavior; and
- an independent reviewer returns a no-findings/approval verdict for the exact head.
