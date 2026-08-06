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
5. Permit any `LD_*`, `DYLD_*`, `PYTHONPATH`, `PYTHONHOME` or `GIT_*` variable
   in a catalog command environment.
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
10. Mutate a catalog-owned `ProjectCommandSpec` after the catalog snapshot is
    taken.
    Expected: `test_materialization_deep_copies_catalog_specs` fails unless the
    catalog owns a deep copy of every command spec.
11. Mutate the original `Toolchain._bindings` from the injected isolation
    verifier after the attested toolchain hash has been checked.
    Expected: `test_materialization_uses_attested_toolchain_snapshot` fails unless
    binding resolution uses the same immutable snapshot that was hashed.
12. Mutate a toolchain-owned `ToolBinding` after the snapshot is taken.
    Expected: `test_materialization_deep_copies_tool_bindings` fails unless the
    toolchain owns a deep copy of every binding.
13. Replace `materializer.executable_verifier` from inside the isolation verifier
    callback.
    Expected: `test_materialization_uses_original_executable_verifier_snapshot`
    fails unless the originally reviewed verifier is used and retained.
14. Reuse or retarget a registry materialized for task A with task B that grants
    the same command ID but has a different task hash or base SHA.
    Expected: the task-bound registry regression fails unless registry authority
    is immutable and checked on every resolution.
15. Mutate the caller-owned DevelopmentTask from the isolation callback.
    Expected: the validated-task-snapshot regression fails unless all later
    materialization and registry decisions use the reconstructed snapshot.
16. Accept a lowercase or malformed persisted task ID.
    Expected: schema and reload regressions fail.
17. Accept a directly constructed task whose `base_sha` is a moving ref such as
    `main` and issue a GitHub request before validation.
    Expected: `test_invalid_direct_task_sha_fails_before_network` fails.
18. Retarget any GitHub adapter authority after construction, including task
    snapshot, repository path, token, timeout or transport.
    Expected: `test_validated_adapter_authority_cannot_be_retargeted` fails unless
    the complete adapter authority is sealed and the original request metadata
    remains in force.
19. Accept `200.0` as a persisted receipt status because it compares equal to
    integer `200` in Python.
    Expected: `test_receipt_reload_types_and_task_binding_are_strict` fails.
20. Materialize the reviewed catalog without an injected isolation verifier.
    Expected: the default fail-closed materialization regression fails.
21. Let `HTTPS_PROXY`, `SSL_CERT_FILE`, `SSL_CERT_DIR` or environment-resolved
    CA paths choose the network or TLS trust authority used for GitHub reads.
    Expected: `test_transport_ignores_environment_network_and_tls_authority`
    fails unless proxy inheritance is empty and an explicit TLS client context
    loads only compiled OpenSSL paths or explicit Windows certificate stores.
