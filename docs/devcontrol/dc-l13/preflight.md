# DC-L13 preflight

**Base:** `main @ 9cd0f909dc72a1ca1a1ee895dacff43b1b51cb78`

**Locked source:** PR #338 @ `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`

**Raw import:** `ae00850f1569b5a6f0bc15d028ba387a069154cf`

## Scope

DC-L13 lands deterministic local-only candidate materialization over one exact verified DC-L12 preflight chain. It may create a candidate commit and proposed branch only inside a newly initialized isolated bare repository. Source state, staged trusted-Git runtime evidence, tree object, commit object, branch ref and canonical receipt are rebound and re-verified before acceptance.

The locked source contains six exact paths. The progressive landing adds a static internal support package, a dedicated fail-closed boundary test, foundation and workflow inventory updates, and a load-bearing CI gate.

## Hard exclusions

No configured remote, non-file transport, network fetch, push, credential helper, private-key API, signer, GitHub adapter, pull-request mutation, reviewer request, ready conversion, merge, release, deployment or activation authority is in scope.

The historical dynamic legacy proxy and `_compatibility_v1` package are not distributed. Package root, Tier-A facade and the legacy ToolHost bundle remain free of DC-L13 exports.
