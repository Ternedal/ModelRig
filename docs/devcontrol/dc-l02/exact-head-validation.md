# DC-L02 exact-head validation

Status: **pending exact-head CI**

The final candidate must prove all of the following on one immutable PR head:

- changed paths equal `exact-path-allowlist.json` exactly (27 paths);
- branch merge base equals the recorded fresh `main` base;
- all nine exact-copy blobs match the locked source values;
- all five assigned-source projections remain dependency-minimal;
- `streaming_publication.py` is absent from the diff;
- all eight DC-L01–L02 unittest modules are reached;
- stale dead/zombie-owner locks are reclaimed while live or unverifiable locks fail closed;
- the per-campaign kernel guard serializes stale reclaim and the critical section;
- parent-directory durability regressions execute for POSIX and the Windows flush primitive;
- persisted campaign and task metadata are validated during reload;
- package import remains dormant and product code does not import DevControl;
- all repository workflows are successful.

Any head change invalidates the result.
