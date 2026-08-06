# DC-L02 preflight

- Slice: `DC-L02 — Durable campaign, store and structural review`
- Fresh branch: `agent/devcontrol-dc-l02-durable-campaign`
- Exact branch base: `main @ a4260a4633125246fb67f7316dcc7e5e1dae6700`
- Dependency satisfied: DC-L01 merged through PR #355
- Locked source reference: PR #338 at `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`
- Assigned source paths: 14
- Progressive surfaces: 4
- Slice-control artifacts: 8
- Complete allowlist: 26 paths
- Hard exclusion: `devcontrol/src/kaliv_dev_control/streaming_publication.py`

## Required finding closures

1. Campaign-store lock recovery must reclaim a lock only when its recorded owner
   is provably dead or its stable process identity no longer matches.
2. Campaign-store directory-entry mutations must be crash durable: newly created
   parent directories, lock create/reclaim/release, create-once records, atomic
   replacement and cleanup all bind to the parent-directory durability primitive.

## Authority boundary

The slice remains local and dormant. It adds no network write, remote Git,
credential, GitHub mutation, merge, release, deployment or activation authority.
Human-only merge authority remains unchanged.
