# V1 repository-authority preflight — actual frozen tool interfaces (2026-10-09)

**Status: OPERATOR GUIDANCE ONLY — NOT A RELEASE RECEIPT.** This document
addresses the cross-repository interface gap tracked in
[ModelRig #2109](https://github.com/Ternedal/ModelRig/issues/2109).
Follow [V1 physical campaign #2025](https://github.com/Ternedal/ModelRig/issues/2025)
and [V1 convergence #1994](https://github.com/Ternedal/ModelRig/issues/1994).
It does not change repository settings, enable any feature or authorize a release.

## Frozen software identity

| Repository | Required exact `main` SHA |
| --- | --- |
| ModelRig | `0b2ff455116f4f28a1a41704d9cb81503f17d2df` |
| BodyRig | `8a85597637d0b59947bd179366e27be1bb847c16` |
| VisionRig | `66ea9bfce1c4d219e4bac1d85324a0e6e3f042e5` |
| VoiceRig | `9f3e594996db7eb2c6e035247ecb168bf17c1dae` |

All four exact software revisions have the previously qualified
`software_exact_green` evidence. Any movement of a frozen repository SHA
requires explicit re-freeze and requalification, not silent substitution.

## Step 1 — observe existing local checkouts, do not change them

Run the following commands in **PowerShell 7** on the actual rig. This is a
read-only preflight: no `git pull`, `checkout`, `reset`, package installation,
credential printing, restart or repository-setting writes.

```powershell
$expected = [ordered]@{
  ModelRig  = '0b2ff455116f4f28a1a41704d9cb81503f17d2df'
  BodyRig   = '8a85597637d0b59947bd179366e27be1bb847c16'
  VisionRig = '66ea9bfce1c4d219e4bac1d85324a0e6e3f042e5'
  VoiceRig  = '9f3e594996db7eb2c6e035247ecb168bf17c1dae'
}
$rootBase = 'C:\Rig\src'
foreach ($name in $expected.Keys) {
  $root = Join-Path $rootBase $name
  if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "Missing checkout: $root"
  }
  $branch = (& git -C $root branch --show-current)
  if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') {
    throw "$name is not on main"
  }
  $head = (& git -C $root rev-parse HEAD)
  if ($LASTEXITCODE -ne 0 -or $head -ne $expected[$name]) {
    throw "$name HEAD does not equal pinned V1 SHA"
  }
  $porcelain = @(& git -C $root status --porcelain)
  if ($LASTEXITCODE -ne 0 -or $porcelain.Count -gt 0) {
    throw "$name checkout is not clean"
  }
  Write-Host "$name exact frozen clean main: OK ($head)"
}
```

If one checkout is missing, dirty or on a different SHA, **stop**.
Do not fix it by force-resetting, deleting files or advancing main.

## Step 2 — inspect GitHub access, read only

`gh auth status -h github.com` confirms that GitHub CLI is authenticated
without printing an access token. API access to branch protection may still
be forbidden (403); a denied/partial response is **not a PASS**.

**Actual root verifier interfaces at the frozen SHAs**:

| Repository | Exact operator command | Evidence limitation |
| --- | --- | --- |
| ModelRig | `& C:\Rig\src\ModelRig\verify-repository-authority.ps1 -Json` | JSON evaluation; script verifies clean `main` checkout and HEAD, but final release gate still needs independently reviewed provenance |
| BodyRig | `& C:\Rig\src\BodyRig\verify-repository-authority.ps1 -Json` | JSON evaluation; script verifies clean `main` checkout and HEAD, same review boundary |
| VisionRig | `& C:\Rig\src\VisionRig\verify-repository-authority.ps1` | **Text only; NO `-Json`**. No exact-HEAD checkout binding inside verifier |
| VoiceRig | `& C:\Rig\src\VoiceRig\verify-repository-authority.ps1` | **Text only; NO `-Json`**. No exact-HEAD checkout binding inside verifier |

The tools require `gh` read permission for live repository protection.
The VisionRig and VoiceRig legacy scripts fetch
`repos/Ternedal/<repo>/branches/main/protection` and check selected branch
protection fields. Even if one prints `Repository authority: PASS`, this is
an **operator observation only**, not an SHA-bound immutable source receipt.
Never run those two with `-Json`: they declare `param()`.

The PowerShell commands above invoke the existing scripts only; their results
have **not** been executed or verified as PASS in this document. Consult the
two scripts' actual `exit` codes and substantive output. Capture resulting
information in secure local validation storage. Do not post credentials, tokens
or raw operator-environment details to public GitHub issues.

## Step 3 — canonical source review and release boundary

ModelRig's canonical
`scripts/kaliv_repository_authority_qualifier.py` consumes a reviewed
`kaliv-system/repository-authority-evidence/v1` input consisting of exact
`git_sha`, `live_repository_authority_passed`, and a distinct
`evidence_ref` for each core repository. It validates envelope structure,
canonical repository set and SHA/ref forms. **It does not invoke the
four live verifiers or independently authenticate opaque refs.**

Do **not** hand-author `live_repository_authority_passed=true` or fabricate
`evidence_ref` to obtain an apparent green qualification. Until independently
reviewed, SHA-bound, immutable live source evidence exists for **all four**
repositories, keep the canonical system gate
`repository_authority=PENDING`. The VisionRig/VoiceRig structured
verifier/evidence integration is tracked in
[#2109](https://github.com/Ternedal/ModelRig/issues/2109).

No local policy observation, test fixture, old artifact or documentation update
can substitute for actual protected-branch administration semantics, including
required checks and their app identity, review rules, force-push/deletion
restrictions, bypass and administrator enforcement. Only the reviewed canonical
four-repo release qualifier may emit a gate receipt.

**Unchanged:** `release_ready=false`, `production_activation=false`.
Do not create `v2.0.14`, perform software merges or enable production on
the strength of this preflight.
