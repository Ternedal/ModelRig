# DC-L03 mutation results

Status: **mutations designed; exact-head CI pending**

Load-bearing mutations and expected failures:

1. Replace the returned Git blob SHA with another valid 40-hex value.
   Expected: `test_blob_sha_and_size_mismatches_are_rejected` fails.
2. Remove protected-path or `.git` rejection.
   Expected: the pre-network scope regression fails and records a transport call.
3. Permit redirects or a non-`api.github.com` authority.
   Expected: redirect/fixed-authority regressions fail.
4. Serialize or echo the bearer token into a receipt.
   Expected: the token-redaction assertion fails.
5. Permit `LD_PRELOAD`, `LD_AUDIT`, `DYLD_*`, `PYTHONPATH` or `GIT_*` in a
   catalog command environment.
   Expected: the catalog isolation-environment regression fails.
6. Execute the original pathname after verification instead of the sealed
   verified object.
   Expected: `test_sealed_executable_object_is_launched_after_source_replacement`
   fails after `os.replace()` swaps the pathname to unverified bytes.
7. Follow a linked executable or accept an executable hash mismatch.
   Expected: the linked executable/hash regression fails.
8. Accept a lowercase or malformed persisted task ID.
   Expected: schema and reload regressions fail.
9. Accept `200.0` as a persisted receipt status because it compares equal to
   integer `200` in Python.
   Expected: `test_receipt_reload_types_and_task_binding_are_strict` fails.
10. Materialize the reviewed catalog without an injected isolation verifier.
    Expected: the default fail-closed materialization regression fails.
