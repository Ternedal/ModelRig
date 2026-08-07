# DC-L03 mutation results

Status: **final exact-head rerun pending**

Load-bearing negative cases:

1. Any default command ID, Python command spec, Go command spec or direct use of
   the reserved sandbox tool must fail closed.
2. A task granting a removed command ID must fail before executable verification
   or launch authority is created.
3. A fake executable verifier must be rejected; materialization uses the fixed
   descriptor-bound static-runtime verifier.
4. Both the containment helper and every future custom tool must reject ELF
   objects containing `PT_INTERP` or `PT_DYNAMIC`, malformed program tables,
   links, FIFOs, hash mismatches, path swaps and oversized input.
5. Verified bytes must be copied into a sealed memfd and execution must use that
   pinned object rather than reopening the pathname.
6. Catalog environment mutation must reject hostile PATH, locale, timezone,
   loader, Python, Go and Git authority.
7. Task, catalog, toolchain, executable verifier and isolation proof mutation
   must not retarget materialization or receipts.
8. GitHub protected paths and `.git` must fail before transport.
9. GitHub host, method and ref must remain fixed to GET requests against
   `api.github.com` at the exact task SHA.
10. Redirects, environment proxies, environment-selected TLS roots, automatic
    reconnects and post-deadline sends must remain disabled.
11. Response size, base64, declared length and computed Git blob identity must be
    verified before evidence is issued.
12. Tokens must never be serialized; receipt identity, integer fields and bounds
    must reload strictly.
13. The complete candidate diff must remain exactly the 16 allowlisted paths and
    0 commits behind `main`.

The final evidence head requires all repository workflows and a fresh independent
review. No merge-readiness verdict is claimed by this artifact alone.
