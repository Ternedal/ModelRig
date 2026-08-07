# DC-L03 exact-head validation

Status: **final evidence head pending its own workflows and independent review**

Base and scope:

- base: `main @ c9bda459f10e682ec200fdfea8484d726c6c0057`;
- complete diff: exactly the 16 paths in `exact-path-allowlist.json`;
- branch distance: 0 commits behind `main`;
- package activation and `default_registry()` unchanged;
- no merge, release, deployment or activation authority.

Validated properties before the final documentation head:

- empty default ModelRig command catalog;
- fail-closed rejection of Python, Go and direct sandbox command specs;
- future custom tools and the containment helper must be descriptor-pinned,
  hash-verified, sealed static ELF objects without `PT_INTERP` or `PT_DYNAMIC`;
- immutable task, catalog, toolchain and isolation-attestation snapshots;
- private verifier proof with post-callback canonical authority revalidation;
- fixed process values for `PATH`, `LANG`, `LC_ALL`, `LC_CTYPE` and `TZ`;
- fixed-host HTTPS GET-only GitHub reads at the exact task SHA;
- disabled redirects, environment proxies and environment-selected TLS roots;
- one monotonic deadline across setup, request, framing and body reads;
- bounded JSON/base64 handling, Git-blob identity verification and strict,
  token-free receipt reload.

The runtime candidate immediately before this evidence update passed CodeQL,
agent3-diagnostics and agent3-full-diagnostics. Its first CI attempt identified
only an invalid zero-command test fixture; the corrected fixture uses a valid
DevelopmentTask while proving that the empty default catalog rejects the removed
command before any launch authority can be created.

The final exact head must independently pass:

- `ci`;
- `codeql`;
- `agent3-diagnostics`;
- `agent3-full-diagnostics`;
- a fresh Codex review with no actionable thread.

No final merge-readiness conclusion is claimed in this file until those exact-head
gates complete.
