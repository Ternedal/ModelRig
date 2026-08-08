# DC-L12 preflight

**Base:** `main @ e2fa62570833c14faea1575c2739f7bcc88fde3d`

**Locked source:** PR #338 @ `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`

## Scope

DC-L12 lands one-time Ed25519 publisher authorization, durable replay prevention, dual-role authenticated recovery, the physically primary recovery ledger, deterministic v3 receipt finalization and an externally anchored rollback-safe keyring verifier.

The original source set contains 36 locked paths. The landing projection removes the rejected dynamic v1 compatibility authority, retains v1 schemas as historical data only, removes DC-L13 materialization assumptions and adds a static non-signing support namespace plus an external monotonic keyring-state boundary.

## Hard exclusions

No private-key API, signer, HMAC issuer, shared secret, credential loader, Git client, subprocess publisher, HTTP/GitHub client, remote write, branch/push/PR mutation, reviewer request, ready-for-review, merge, release, deployment, activation or DC-L13 materialization authority is in scope.

Package root, Tier-A facade and the v7 execution bundle remain free of DC-L12 authority exports.