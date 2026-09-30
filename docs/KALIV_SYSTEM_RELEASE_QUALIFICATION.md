# Kaliv system release qualification

A green repository is not the same thing as a finished Kaliv system.

`scripts/kaliv_system_release_gate.py` is the fail-closed final qualification
boundary for a **cross-repository release candidate**. It binds the candidate to
exact Git SHAs and requires evidence for the physical/runtime gates that normal CI
cannot prove.

## Required repository pins

A v1 manifest must pin at least these repositories to lowercase 40-hex Git SHAs:

- `Ternedal/ModelRig`
- `Ternedal/BodyRig`
- `Ternedal/VisionRig`
- `Ternedal/VoiceRig`

Additional clients/renderers may be pinned as extra repository entries. Mutable
names such as `main`, tags or branch names are never accepted as release
identity.

## Required gates

All eight gates must be `PASS`, and every PASS must carry at least one explicit
evidence reference:

1. `software_exact_green` — exact pinned repository revisions qualified by their
   software checks.
2. `consciousness_live_lifecycle` — a real live Core lifecycle covering
   continuity, wake/dormancy and model replacement without identity drift.
3. `visionrig_physical_perception` — real sensor input reaches bounded
   WorldEvidence/WorldState through the accepted VisionRig boundary.
4. `bodyrig_photoreal_likeness` — the real-person Photoreal likeness gate,
   including required human review, has passed.
5. `bodyrig_digital_twin_m6` — one coherent Person lineage reaches canonical M6
   with the required physical/human Windows and Quest evidence.
6. `end_to_end_latency` — one correlated real event traverses perception,
   cognition and outward voice/body behavior with measured latency evidence.
7. `recovery_soak` — the pinned system passes the agreed restart/recovery and
   long-running soak campaign.
8. `repository_authority` — the repositories used for the release are protected
   by the accepted exact-green merge authority.

A missing or failed gate yields `BLOCKED`. A PASS without evidence is malformed,
not merely pending.

## Authority boundary

The gate intentionally cannot activate production. The manifest must contain:

```json
"production_activation": false
```

and the emitted verdict also keeps `production_activation=false` even when all
eight gates qualify. Final activation remains owned by the existing explicit
release/physical authorities.

This is deliberate: neither this script nor CI may synthesize Photoreal,
human-review, physical-rig, soak or production-activation evidence.

## Example

```json
{
  "schema": "kaliv-system-release-manifest/v1",
  "release_id": "kaliv-rc-1",
  "repositories": [
    {"repository": "Ternedal/ModelRig", "git_sha": "<40-hex>"},
    {"repository": "Ternedal/BodyRig", "git_sha": "<40-hex>"},
    {"repository": "Ternedal/VisionRig", "git_sha": "<40-hex>"},
    {"repository": "Ternedal/VoiceRig", "git_sha": "<40-hex>"}
  ],
  "gates": {
    "software_exact_green": {"status": "PASS", "evidence_refs": ["..."]},
    "consciousness_live_lifecycle": {"status": "PENDING", "evidence_refs": []},
    "visionrig_physical_perception": {"status": "PENDING", "evidence_refs": []},
    "bodyrig_photoreal_likeness": {"status": "PENDING", "evidence_refs": []},
    "bodyrig_digital_twin_m6": {"status": "PENDING", "evidence_refs": []},
    "end_to_end_latency": {"status": "PENDING", "evidence_refs": []},
    "recovery_soak": {"status": "PENDING", "evidence_refs": []},
    "repository_authority": {"status": "PENDING", "evidence_refs": []}
  },
  "production_activation": false
}
```

Run:

```powershell
python scripts/kaliv_system_release_gate.py .\path\to\kaliv-release-manifest.json
```

Exit code 0 means all eight evidence gates qualify. Exit code 1 means a valid
manifest is still blocked. Exit code 2 means the manifest itself is invalid.

## Binding qualified Consciousness evidence

Do not mark the consciousness_live_lifecycle gate PASS by hand. Once
scripts/consciousness_live_lifecycle_qualifier.py has produced a QUALIFIED
verdict for the exact pinned ModelRig SHA, bind it into the release manifest with:

    python scripts/kaliv_system_release_bind_consciousness.py ^
      .\kaliv-release-manifest.json ^
      .\consciousness-live-lifecycle-verdict.json ^
      --output .\kaliv-release-manifest.bound.json

The binder validates the exact ModelRig SHA, all lifecycle qualification flags,
the release_evidence_ref prefix/digest shape, and all no-authority /
production_activation=false constraints. It may change only the
consciousness_live_lifecycle gate. An explicit FAIL is never overwritten, and an
existing PASS is accepted only when it already references the exact same
qualified evidence.

