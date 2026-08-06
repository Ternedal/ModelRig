# DC-L03 independent review verdict

Status: **pending fresh exact-head review**

Independent review of `96967da26134cb68cc59242fbee004cc403228ba`
found two actionable issues:

1. the injected isolation verifier received an authority object that could be
   mutated after the materializer's initial comparison;
2. executable verification opened a candidate with blocking `O_RDONLY`, allowing
   a FIFO with no writer to hang before regular-file validation.

Candidate `660e85dcb0281cdbc0991d9cb5c06a7f0064ff6f` closes both findings with:

- private reconstructed attestation snapshots before and after the callback;
- canonical and authority revalidation after the callback;
- `O_NONBLOCK` on the no-follow descriptor open;
- executable regressions for callback mutation and FIFO rejection without a
  writer.

The focused suite passes **26/26 tests**. No final independent verdict is claimed
until the resulting evidence head is reviewed without an actionable finding.

Required review focus:

1. immutable catalog and toolchain canonicalization;
2. exact task/catalog/toolchain/attestation binding before materialization and
   after the external isolation-verifier callback;
3. fail-closed default isolation and Windows executable verification;
4. POSIX executable link, mutation, non-regular-file, FIFO and size handling;
5. fixed GET-only GitHub host/method/ref authority;
6. explicit TLS trust roots independent of `SSL_CERT_FILE`, `SSL_CERT_DIR` and
   environment proxy configuration;
7. task-scope and protected-path enforcement before network access;
8. response/file bounds, JSON/base64 validation and Git blob identity;
9. token non-persistence and receipt determinism;
10. absence of write, remote Git, publication, merge or activation authority.
