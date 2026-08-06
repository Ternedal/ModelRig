# DC-L02 exact-head validation

Status: **successful on implementation candidate**

Implementation candidate: `952da3c1409c6f5a34833b248cdb7c498e97d1f8`
Fresh branch base / merge base: `a4260a4633125246fb67f7316dcc7e5e1dae6700`

Successful workflows on the implementation candidate:

- CI #2916
- CodeQL #1932
- agent3-diagnostics #1085
- agent3-full-diagnostics #2166

Verified:

- changed paths equal `exact-path-allowlist.json` exactly (27 paths);
- the branch is 0 commits behind its recorded fresh `main` base;
- all nine exact-copy blobs match the locked source values;
- all five assigned-source projections are dependency-minimal and documented;
- `streaming_publication.py` is absent from the diff;
- all eight DC-L01–L02 unittest modules are reached;
- stale dead/zombie-owner locks are reclaimed while live or unverifiable locks fail closed;
- the per-campaign kernel guard serializes stale reclaim and the complete critical section;
- parent-directory durability regressions execute for POSIX and the Windows flush primitive;
- persisted campaign and task metadata are validated during reload;
- package import remains dormant and product code does not import DevControl;
- all four prior review findings are resolved.

This evidence-only update must itself receive green workflows before the PR is marked ready. Any later head change invalidates the final result.
