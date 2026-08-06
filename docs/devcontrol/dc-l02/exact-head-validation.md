# DC-L02 exact-head validation

Status: **pending exact-head CI**

The final candidate must prove all of the following on one immutable PR head:

- changed paths equal `exact-path-allowlist.json` exactly;
- branch merge base equals the recorded fresh `main` base;
- all ten exact-copy blobs match the locked source values;
- all four projections remain dependency-minimal;
- `streaming_publication.py` is absent from the diff;
- all eight DC-L01–L02 unittest modules are reached;
- stale dead-owner locks are reclaimed, live or unverifiable locks fail closed;
- parent-directory durability regressions execute;
- package import remains dormant and product code does not import DevControl;
- all repository workflows are successful.

Any head change invalidates the result.
