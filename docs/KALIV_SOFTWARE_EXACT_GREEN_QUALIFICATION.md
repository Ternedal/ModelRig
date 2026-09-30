# Kaliv software exact-green qualification

`scripts/kaliv_software_exact_green_qualifier.py` produces the canonical
cross-repository evidence for the `software_exact_green` system-release gate.

It does **not** run CI itself and it does not infer physical readiness. It
validates reviewed exact-head software evidence for the four core repositories:

- `Ternedal/ModelRig`
- `Ternedal/BodyRig`
- `Ternedal/VisionRig`
- `Ternedal/VoiceRig`

Each repository entry must carry an immutable 40-hex Git SHA, an explicit
`exact_head_qualified=true`, `software_green=true`, and a distinct bounded
software-evidence reference. Mutable names such as `main`, tags or branch names
are rejected as revision identity.

A successful verdict emits:

```text
kaliv-software-exact-green:<modelrig-sha>:<bodyrig-sha>:<visionrig-sha>:<voicerig-sha>:<sha256>
```

The final system-release gate compares all four embedded SHAs with the release
manifest pins. A PASS therefore cannot be reused for a different BodyRig,
VisionRig or VoiceRig revision merely because ModelRig stayed unchanged.

The qualifier is software-only. Its verdict always keeps:

```json
{
  "software_exact_green_gate_satisfied": true,
  "release_gate_satisfied": false,
  "production_activation": false
}
```

It does not satisfy lifecycle, physical perception, Photoreal likeness, M6
digital-twin, Android live-body, latency, soak, repository-authority, or final
production activation.

## Input shape

```json
{
  "schema": "kaliv-system/software-exact-green-evidence/v1",
  "repositories": [
    {
      "repository": "Ternedal/ModelRig",
      "git_sha": "<40-hex>",
      "exact_head_qualified": true,
      "software_green": true,
      "evidence_ref": "github-actions:<immutable-ref>"
    }
  ],
  "production_activation": false
}
```

All four required repositories must appear exactly once.

## Run

```powershell
python scripts/kaliv_software_exact_green_qualifier.py .\software-evidence.json `
  --report .\validation\kaliv-software-exact-green-latest.json
```

Exit code 0 means the supplied software evidence is structurally qualified.
Exit code 2 means it is malformed, incomplete, not exact-head green, or
overclaims authority.
