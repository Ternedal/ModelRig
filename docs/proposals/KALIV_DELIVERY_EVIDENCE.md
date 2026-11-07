# Kaliv delivery control — evidence ledger

This document distinguishes evidence from plans. It must be updated with new
verified runs; historical success does not prove later commits are green.

## Verified offline report chain

- Commit: `a2300d1eb23c2750a1462aef2830f03cc06ff65e`
- Workflow run: https://github.com/Ternedal/ModelRig/actions/runs/39945547533
- Conclusion: **success**, verified via GitHub workflow run API.
- Artifact: `kaliv-delivery-SYNTHETIC-demo`, artifact ID `12497936649`.
- Artifact expiry: 2026-10-30 11:22 UTC (GitHub metadata).
- Evidence: artifact exists, is not expired at inspection time, and is attached
  to the verified run. It is synthetic and **not live repository status**.

## Not yet verified

- Manual live snapshot across all ten repositories.
- Fine-grained read-only token provisioning and permissions.
- Real issue/PR/workflow counts for all ten repositories.
- End-to-end user journey, physical acceptance, or production readiness.
- Scheduled reporting, notification or automatic blocker escalation.

## Promotion gate

1. Review collector code and access scope.
2. Provision least-privilege token via GitHub Actions secret
   `KALIV_REPORT_READ_TOKEN`; never store it in source.
3. Make manual workflow available on the default branch through normal PR
   review and required checks, without bypassing protections.
4. Run manually; inspect `kaliv-delivery.json` and `kaliv-delivery.md`.
5. Check unknowns, truncated data and access failures; reconcile with GitHub UI.
6. Only then consider a scheduled read-only snapshot; no automated merges.

See [operations](KALIV_DELIVERY_SNAPSHOT_OPERATIONS.md) and
[master roadmap](KALIV_MASTER_ROADMAP.md).
