# DC-L05 preflight

Status: **draft candidate; exact-head validation pending**

## Base and dependency lock

- branch base: `main @ a1fe16f05ba312e719b1254bba9919809bab4215`;
- DC-L04 merged through PR #384;
- locked source: PR #338 at `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`;
- fresh non-stacked branch required.

## Authority boundary

DC-L05 lands only the product-side native Windows containment substrate:

- Job Object enforcement and process-tree termination;
- AppContainer/restricted-token launch and workspace capability handling;
- bounded stdout/stderr capture;
- reviewed environment handling;
- runtime-lifetime guard; and
- dormant Tier-A Windows launch helpers.

It may not add:

- any `kaliv_dev_control` import from product code;
- DevControl command registration, catalog activation or route activation;
- Tier-A authority materialization or a supported DevControl execution facade;
- trusted Git, credentials, GitHub write or remote Git;
- publication, merge, release, deployment or production activation.

## Source projection

The 15 literal DC-L05 source paths are seeded from the locked source head. The
workflow runs only the native substrate contracts. The catalog/closure and
Git-aware receipt support programs are present as dormant source for later slices
and are intentionally not executed here. `worker/requirements.txt` remains
unchanged because its source-branch `cryptography` addition belongs to DC-L10.

## Merge gates

- exact 26-path diff and 0 commits behind `main`;
- all product modules remain free of DevControl imports;
- real-Windows Job Object, AppContainer, bounded-capture, environment and ToolHost
  contracts pass;
- future integration support programs remain inactive;
- all repository workflows pass on the exact head;
- no unresolved review thread remains; and
- independent exact-head approval is required when review capacity is available.
