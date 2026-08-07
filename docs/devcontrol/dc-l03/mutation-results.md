# DC-L03 mutation results

Status: **focused mutations covered; exact-head repository CI pending**

Load-bearing mutations and expected failures:

1. Replace a returned Git blob SHA with another valid 40-hex value.
   Expected: blob-identity regression fails.
2. Remove protected-path or `.git` rejection.
   Expected: pre-network scope regression fails.
3. Permit redirects, proxies or a non-`api.github.com` authority.
   Expected: fixed-authority regressions fail.
4. Serialize the bearer token into a receipt.
   Expected: token non-persistence assertion fails.
5. Permit unreviewed process environment authority.
   Expected: the fixed-value positive-list regression rejects, including
   `GOROOT`, `PYTHONUSERBASE` and non-local `GOTOOLCHAIN`.
6. Execute a pathname after verification instead of its sealed object.
   Expected: pathname-replacement regression fails.
7. Reuse a retired descriptor for an old `/proc/<pid>/fd/<n>` template.
   Expected: descriptor-retirement regression fails.
8. Follow a link, accept a hash mismatch, or wait on a FIFO.
   Expected: link/hash/FIFO regressions fail.
9. Mix catalog command resolution and hashing from different catalog objects.
   Expected: catalog-snapshot regression fails.
10. Mutate a catalog-owned ProjectCommandSpec after snapshot creation.
    Expected: deep-copy regression fails.
11. Mutate Toolchain bindings after attested hashing.
    Expected: toolchain-snapshot regression fails.
12. Mutate a toolchain-owned ToolBinding after snapshot creation.
    Expected: binding deep-copy regression fails.
13. Replace the executable verifier during isolation verification.
    Expected: verifier-snapshot regression fails.
14. Reuse or retarget a registry for another task.
    Expected: exact-task registry regression fails.
15. Mutate the caller-owned task or verifier-owned attestation.
    Expected: private task/proof snapshot regressions fail.
16. Accept malformed receipt fields, repository syntax or `200.0` status.
    Expected: runtime/schema reload regressions fail.
17. Accept a moving base ref before transport.
    Expected: exact-SHA pre-network regression fails.
18. Retarget adapter task, repository, token, timeout or transport.
    Expected: sealed-adapter regression fails.
19. Materialize without independently supplied isolation evidence.
    Expected: fail-closed default regression fails.
20. Let environment proxy or CA settings choose GitHub authority.
    Expected: explicit proxy/TLS trust regression fails.
21. Return a slow-drip response that always emits a byte before each inactivity
    timeout.
    Expected: the monotonic deadline regression fails unless every read uses the
    remaining total budget and the response is closed on expiry.
22. Hide the underlying response socket so the deadline cannot be applied.
    Expected: transport fails closed before accepting body evidence.

The latest complete focused runtime run produced **26/26 passing tests** before
the final environment/deadline changes. Those final findings have additional
executable contract regressions and clean, narrowly scoped commit diffs. Full
exact-head CI and diagnostics remain pending because no Actions run has been
created for connector-authored heads.
