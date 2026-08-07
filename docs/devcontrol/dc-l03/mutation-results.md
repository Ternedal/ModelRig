# DC-L03 mutation results

Status: **focused mutations covered; exact-head repository CI pending**

Load-bearing mutations and expected failures:

1. Replace a returned Git blob SHA with another valid 40-hex value.
   Expected: blob-identity regression fails.
2. Remove protected-path or `.git` rejection.
   Expected: pre-network scope regression fails and records a transport call.
3. Permit redirects, proxies or a non-`api.github.com` authority.
   Expected: fixed-authority regressions fail.
4. Serialize the bearer token into a receipt.
   Expected: token non-persistence assertion fails.
5. Permit `LD_*`, `DYLD_*`, `PYTHONPATH`, `PYTHONHOME` or `GIT_*` catalog
   environment authority.
   Expected: catalog environment regression fails.
6. Execute the pathname after verification instead of the sealed object.
   Expected: sealed-object regression fails after pathname replacement.
7. Reuse a retired descriptor number for an old `/proc/<pid>/fd/<n>` template.
   Expected: descriptor-retirement regression fails.
8. Follow a linked executable or accept a hash mismatch.
   Expected: link/hash regression fails.
9. Mix command resolution from one catalog with the hash of another.
   Expected: catalog-snapshot regression fails.
10. Mutate a catalog-owned ProjectCommandSpec after snapshot creation.
    Expected: deep-copy regression fails.
11. Mutate Toolchain bindings after attested hashing.
    Expected: toolchain-snapshot regression fails.
12. Mutate a toolchain-owned ToolBinding after snapshot creation.
    Expected: binding deep-copy regression fails.
13. Replace the executable verifier during the isolation callback.
    Expected: verifier-snapshot regression fails.
14. Reuse or retarget a registry for another task with the same command ID.
    Expected: task-bound registry regression fails.
15. Mutate the caller-owned DevelopmentTask during isolation verification.
    Expected: task-snapshot regression fails.
16. Accept malformed persisted task IDs or receipt field types.
    Expected: schema/reload regressions fail.
17. Accept a moving base ref such as `main` before transport.
    Expected: pre-network exact-SHA regression fails.
18. Retarget adapter task, repository, token, timeout or transport authority.
    Expected: sealed-adapter regression fails.
19. Accept `200.0` as a persisted receipt status.
    Expected: strict integer-status regression fails.
20. Materialize without an independently supplied isolation verifier.
    Expected: fail-closed default regression fails.
21. Let `HTTPS_PROXY`, `SSL_CERT_FILE` or `SSL_CERT_DIR` choose network/TLS
    authority.
    Expected: explicit proxy/TLS trust regression fails.
22. Mutate the IsolationAttestation received by the verifier callback.
    Expected: private-snapshot/post-callback regression fails.
23. Present an executable FIFO with no writer.
    Expected: FIFO regression times out unless open is nonblocking and the file
    is rejected as non-regular before reading.
24. Permit receipt repository identities containing owner/name dot segments,
    whitespace or NUL in the JSON schema while runtime rejects them.
    Expected: workflow contract schema-alignment regression fails.

Focused runtime validation remains **26/26 passing tests**. The repository
contract additionally validates the canonical receipt repository pattern. Full
repository CI and diagnostics remain pending because no Actions run has been
created for the connector-authored exact head.
