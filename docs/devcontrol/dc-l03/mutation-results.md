# DC-L03 mutation results

Status: **mutations designed; exact-head CI pending**

Load-bearing mutations and expected failures:

1. Replace the returned Git blob SHA with another valid 40-hex value.
   Expected: `test_blob_sha_mismatch_is_rejected` fails.
2. Remove protected-path or `.git` rejection.
   Expected: the pre-network scope regression fails and records a transport call.
3. Permit redirects or a non-`api.github.com` authority.
   Expected: redirect/fixed-authority regressions fail.
4. Serialize or echo the bearer token into a receipt.
   Expected: the token-redaction assertion fails.
5. Permit `LD_PRELOAD`, `LD_AUDIT`, `DYLD_*`, `PYTHONPATH` or `GIT_*` in a
   catalog command environment.
   Expected: the catalog isolation-environment regression fails.
6. Follow a linked executable or hash by reopening its pathname.
   Expected: the linked executable/descriptor verification regression fails.
7. Accept a lowercase or malformed persisted task ID.
   Expected: schema and reload regressions fail.
8. Materialize the reviewed catalog without an injected isolation verifier.
   Expected: the default fail-closed materialization regression fails.
