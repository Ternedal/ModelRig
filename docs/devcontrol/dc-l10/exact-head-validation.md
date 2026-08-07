# DC-L10 exact-head validation

**Status:** pending final freeze.

The final entry must record one immutable pull-request head with:

- base `main @ adf8347f99612e8664c13b23ef268d387dec6d6c` or a documented refreshed base;
- exactly 28 changed paths matching `exact-path-allowlist.json`;
- zero commits behind `main`;
- all fifteen source blobs matching `source-provenance.json`;
- all 35 DevControl modules passing;
- the explicit DC-L09 execution and DC-L10 offline-authority boundaries passing;
- repository, Windows, Android, desktop, DPAPI and Browser Use gates passing;
- `ci`, `codeql`, `agent3-diagnostics` and `agent3-full-diagnostics` successful on
  the same exact head;
- zero unresolved review threads; and
- no claim of private signing, model-provider review, remote publication or
  activation authority.

Any head change invalidates the recorded workflow evidence and review verdict.
