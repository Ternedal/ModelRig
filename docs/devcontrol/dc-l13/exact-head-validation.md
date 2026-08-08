# DC-L13 exact-head validation

**Status:** implementation candidate in progress; final control-package-head rerun required.

The mergeable head must prove:

- base `main @ 9cd0f909dc72a1ca1a1ee895dacff43b1b51cb78` or a documented refreshed base;
- exactly 20 changed paths matching `exact-path-allowlist.json`;
- zero commits behind `main`;
- all six raw source identities recorded in `source-provenance.json`;
- the rejected dynamic legacy proxy and `_compatibility_v1` package remain absent;
- all 51 DC-L01–L13 DevControl test modules passing;
- the dedicated DC-L13 local-only materialization boundary passing;
- only `file://` source transfer through `Path.as_uri()` is encoded;
- no remote, non-file transport, push, credential helper, signer, GitHub mutation, reviewer request, ready conversion, merge, release, deployment or activation authority;
- package root, Tier-A facade and ToolHost bundle remain free of DC-L13 exports;
- receipt schemas remain closed with all remote/publication claims fixed to false;
- repository, Windows, Android, desktop, DPAPI and Browser Use gates passing;
- `ci`, `codeql`, `agent3-diagnostics` and `agent3-full-diagnostics` successful on one unchanged exact head;
- zero unresolved review threads; and
- no claim of independent reviewer identity or delegated merge authority.

Any head change invalidates workflow evidence and the review record.
