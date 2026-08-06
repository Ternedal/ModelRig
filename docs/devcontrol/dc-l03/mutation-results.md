# DC-L03 mutation results

Status: **focused mutations covered; exact-head repository CI pending**

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
   Expected: the sealed-object regression fails after `os.replace()` swaps the
   pathname to unverified bytes.
7. Close a verified descriptor and allow its fd number to be reused while an old
   command template still names `/proc/<pid>/fd/<n>`.
   Expected: the sealed-object regression fails after `close()` and an unrelated
   open; the verified descriptor must remain retired until process exit.
8. Follow a linked executable or accept an executable hash mismatch.
   Expected: the linked executable/hash regression fails.
9. Reassign `materializer.catalog` while command IDs are being resolved so the
   selected commands come from one catalog while the checked hash comes from
   another.
   Expected: `test_materialization_uses_attested_catalog_snapshot` fails unless
   one immutable catalog snapshot supplies both command resolution and hashing.
10. Mutate the original `Toolchain._bindings` from the injected isolation
    verifier after the attested toolchain hash has been checked.
    Expected: `test_materialization_uses_attested_toolchain_snapshot` fails unless
    binding resolution uses the same immutable snapshot that was hashed.
11. Accept a lowercase or malformed persisted task ID.
    Expected: schema and reload regressions fail.
12. Accept a directly constructed task whose `base_sha` is a moving ref such as
    `main` and issue a GitHub request before validation.
    Expected: `test_invalid_direct_task_sha_fails_before_network` fails.
13. Allow callers to replace `adapter.task` after construction and make later
    requests dereference the replacement task.
    Expected: `test_validated_task_snapshot_cannot_be_replaced` fails unless all
    requests and receipts use a private immutable validated snapshot.
14. Accept `200.0` as a persisted receipt status because it compares equal to
    integer `200` in Python.
    Expected: `test_receipt_reload_types_and_task_binding_are_strict` fails.
15. Materialize the reviewed catalog without an injected isolation verifier.
    Expected: the default fail-closed materialization regression fails.
