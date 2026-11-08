# Kaliv cross-repository live evidence — partial verification

**Observed:** 2026-10-23 via the connected GitHub search API.
**Scope:** the three P0 tracking issues, not a complete ten-repository snapshot.
**Do not interpret as:** counts of all open issues, CI health, integration
readiness, physical acceptance, or release status.

| Repository | Verified open P0 issue | Evidence |
| --- | --- | --- |
| ModelRig | Trusted actor identity and approval authority | https://github.com/Ternedal/ModelRig/issues/2265 |
| KalivNexus | Read-only NAS/Home Assistant vertical slice | https://github.com/Ternedal/KalivNexus/issues/1 |
| Kaliv | Android/Windows task continuity | https://github.com/Ternedal/Kaliv/issues/2 |

Master coordination issue:
https://github.com/Ternedal/ModelRig/issues/2264

## CI evidence (separate from live snapshot)

The delivery report test workflow for commit
`4be09deb43b359261f13cee69b8861f431e78439`
completed with **success**:
https://github.com/Ternedal/ModelRig/actions/runs/39968571763

This validates the offline test workflow only. It does not demonstrate
successful live report generation across all ten repositories.

## Next required gate

1. Run the manual `Kaliv Delivery Snapshot` workflow after the workflow
   becomes available on the default branch through normal review.
2. Compare JSON/Markdown output against actual GitHub issues, PRs and actions.
3. Record inaccessible repositories explicitly as unknown.
4. Only then decide whether recurring snapshots should be enabled.

**No live snapshot has been claimed or verified here.**
