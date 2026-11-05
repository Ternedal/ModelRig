# Kaliv repository authority qualification

`scripts/kaliv_repository_authority_qualifier.py` produces canonical
cross-repository evidence for the `repository_authority` system-release gate.

It consumes reviewed PASS outputs from the live repository-authority verifiers
in the four core repositories:

- `Ternedal/ModelRig`
- `Ternedal/BodyRig`
- `Ternedal/VisionRig`
- `Ternedal/VoiceRig`

The qualifier itself is read-only. It does not change branch protection,
rulesets, checks, permissions, merge policy, or production activation.

> **V1 operator warning (2026-10-09):** the actual repository
> `verify-repository-authority.ps1` interfaces differ. ModelRig and BodyRig
> accept `-Json`, but VisionRig and VoiceRig are text-only and do not verify
> a clean, SHA-bound checkout. See
> [V1 repository authority preflight](V1_REPOSITORY_AUTHORITY_PREFLIGHT.md)
> and [issue #2109](https://github.com/Ternedal/ModelRig/issues/2109).
> Do not translate a text-only PASS, manually asserted true flag, or
> invented opaque evidence ref into a canonical release PASS. All four live,
> independently reviewed, revision-bound sources are still required.

Each input entry must bind one exact 40-hex Git SHA to
`live_repository_authority_passed=true` and a distinct immutable evidence
reference. Mutable branch or tag identity is rejected.

A successful verdict emits:

```text
kaliv-repository-authority:<modelrig-sha>:<bodyrig-sha>:<visionrig-sha>:<voicerig-sha>:<sha256>
```

The system release gate compares all four embedded revisions against the
release-manifest repository pins. Repository-authority evidence cannot therefore
be reused across a different core-repository revision set.

The verdict keeps:

```json
{
  "repository_authority_gate_satisfied": true,
  "release_gate_satisfied": false,
  "production_activation": false
}
```

A PASS here proves only the reviewed repository-settings authority reports for
the exact pinned repositories. It does not prove physical validation, lifecycle,
Photoreal likeness, M6, latency, soak, Android live body, or final production
activation.

## Run

```powershell
python scripts/kaliv_repository_authority_qualifier.py .\repository-authority-evidence.json `
  --report .\validation\kaliv-repository-authority-latest.json
```

Exit code 0 means all four exact repository-authority reports were accepted.
Exit code 2 means the evidence is malformed, incomplete, mutable, non-PASS, or
overclaims authority.
