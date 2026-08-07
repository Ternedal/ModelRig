# DC-L06 exact-head validation

Status: **pending on the final frozen head**

The seed commit `b40f2313e60d2f1e8f1459ee309ff0585cec8664`
contains only the 15 locked source paths and is not merge evidence.

The final head must prove:

- exactly the 27 paths in `exact-path-allowlist.json` differ from
  `main @ 3ede93313233e65599f2fb29b4c64e58f7432990`;
- the branch is not behind current `main`;
- the seven exact source blobs and twelve documented projections match
  `source-provenance.json`;
- `_tier_a_execution_core.py` owns no class or function and imports only
  already-landed DC-L06 identities;
- materialization binds to the already-landed fixed executable verifier;
- the two literal stage-local bundle tuples are identical and contain no
  L07-or-later module;
- `tier_a_authority.py` exposes no process-launch entrypoint;
- lease, environment, path, materialization, v1-plan and schema tests pass;
- workflow coverage reaches all twenty DevControl modules landed through DC-L06;
- package import remains dormant and product code does not import DevControl;
- portable repository tests, CodeQL and both diagnostics workflows pass; and
- all review threads are resolved.

Workflow run IDs and the exact final SHA are recorded in the pull-request body
after the branch stops changing. A green ancestor does not satisfy this gate.
