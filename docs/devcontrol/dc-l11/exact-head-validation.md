# DC-L11 exact-head validation

**Status:** pending implementation candidate and final freeze.

The mergeable head must prove:

- base `main @ 7c9bc3fefde1e3276e9f4fae452510c90658d114` or a documented refreshed base;
- exactly 26 changed paths matching `exact-path-allowlist.json`;
- zero commits behind `main`;
- all fourteen source blobs matching `source-provenance.json`;
- all 39 DevControl modules passing;
- the DC-L09 execution, DC-L10 offline review and DC-L11 non-mutating intent boundaries passing;
- repository, Windows, Android, desktop, DPAPI and Browser Use gates passing;
- `ci`, `codeql`, `agent3-diagnostics` and `agent3-full-diagnostics` successful on the same exact head;
- zero unresolved review threads; and
- no claim of live publication, one-time authorization, independent reviewer identity, remote mutation, release, deployment or activation authority.

Any head change invalidates workflow evidence and the review record.
