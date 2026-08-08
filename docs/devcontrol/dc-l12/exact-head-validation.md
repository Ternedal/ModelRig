# DC-L12 exact-head validation

**Status:** implementation candidate in progress; final documentation-head rerun required.

The mergeable head must prove:

- base `main @ e2fa62570833c14faea1575c2739f7bcc88fde3d` or a documented refreshed base;
- exactly 51 changed paths matching `exact-path-allowlist.json`;
- zero commits behind `main`;
- all 36 raw source identities recorded in `source-provenance.json`;
- all explicit security projections recorded in `source-path-disposition.json`;
- all 49 DevControl test modules passing;
- DC-L09 execution, DC-L10 semantic review, DC-L11 dry-run and DC-L12 authorization/recovery boundaries passing;
- rollback-safe external keyring generation, drift, epoch and revocation tests passing;
- repository, Windows, Android, desktop, DPAPI and Browser Use gates passing;
- `ci`, `codeql`, `agent3-diagnostics` and `agent3-full-diagnostics` successful on one unchanged exact head;
- zero unresolved review threads; and
- no claim of private signing, live publication, materialization, independent reviewer identity, merge, release, deployment or activation authority.

Any head change invalidates workflow evidence and the review record.