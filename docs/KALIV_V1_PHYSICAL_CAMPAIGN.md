# Kaliv V1 physical campaign — first entrypoint

This branch introduces a **read-only preflight**, not a physical-test PASS or production release.

Run from a PowerShell terminal on the Windows rig:

```powershell
$report = "C:\\Rig\\validation\\v1-preflight-$(Get-Date -Format yyyyMMdd-HHmmss).json"
python C:\\Rig\\src\\ModelRig\\scripts\\kaliv_v1_physical_preflight.py --workspace C:\\Rig\\src --output $report
Get-Content $report
```

The report binds local ModelRig, BodyRig, VisionRig and VoiceRig checkouts to their exact
commit SHAs and reports dirty/missing checkouts. It records availability of git, python,
nvidia-smi and adb without invoking GPU, adb, device pairing or any network endpoint.
It refuses to overwrite an existing report and never mutates a repository.

A clean checkout is **not** enough to qualify a release: preflight always sets
`release_ready=false`, `production_activation=false`, and all ten gates to
`PENDING`. The `READY_FOR_PHYSICAL_QUALIFICATION` status means only that all four
local checkouts exist, have valid Git HEADs, and have no uncommitted changes.

## Follow-on campaign stages (not implemented by this preflight)

1. Resolve and verify exact-head software qualification for all four pinned repositories.
2. Invoke the existing physical qualifiers with their own immutable evidence receipts.
3. Pause for human listening/visual acceptance where the qualifier requires it.
4. Execute recovery and latency measurements on the physical hardware.
5. Feed the independently verified receipts to `kaliv_system_release_gate.py`.
6. Produce a final fail-closed verdict; never equate preflight or CI with physical PASS.

The production release gate remains authoritative. This script cannot approve, merge,
tag, deploy, activate production or synthesize evidence.
