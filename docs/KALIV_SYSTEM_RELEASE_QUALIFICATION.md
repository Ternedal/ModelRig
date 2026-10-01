# Kaliv system release qualification

_Documentation baseline: 2026-10-01 · V1 convergence requires exact repository pins plus independent physical evidence._

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

All nine gates must be `PASS`, and every PASS must carry at least one explicit
evidence reference:

1. `software_exact_green` — exact pinned repository revisions qualified by their
   software checks. A PASS must contain exactly one canonical
   `kaliv-software-exact-green:<modelrig-sha>:<bodyrig-sha>:<visionrig-sha>:<voicerig-sha>:<sha256>`
   reference emitted by `kaliv_software_exact_green_qualifier.py`. All four
   embedded revisions must exactly match the release manifest pins; mutable
   branch/tag labels or evidence for only a subset of the core repositories are
   rejected.
2. `consciousness_live_lifecycle` — a real live Core lifecycle covering
   continuity, wake/dormancy and model replacement without identity drift.
   A PASS must contain exactly one canonical
   `consciousness-live-lifecycle:<modelrig-sha>:<sha256>` reference emitted by
   the lifecycle qualifier. The embedded SHA must equal the pinned ModelRig
   revision, or be an ancestor with the exact same Git tree so a clean GitHub
   merge-commit does not invalidate unchanged physical/runtime evidence.
   Arbitrary labels and component evidence refs are not sufficient.
3. `visionrig_physical_perception` — real sensor input reaches bounded
   WorldEvidence/WorldState through the accepted VisionRig boundary. A PASS must
   contain exactly one canonical
   `visionrig-physical-perception:<visionrig-sha>:<sha256>` reference emitted
   by VisionRig's physical qualifier, and the embedded SHA must equal the pinned
   `Ternedal/VisionRig` revision. A mutable label or inner WorldEvidence ref is
   not sufficient.
4. `bodyrig_photoreal_likeness` — the real-person Photoreal likeness gate,
   including required human review, has passed.
5. `bodyrig_digital_twin_m6` — one coherent Person lineage reaches canonical M6
   with the required physical/human Windows and Quest evidence. A PASS must
   contain exactly one canonical
   `bodyrig-digital-twin-m6:<bodyrig-sha>:<sha256>` reference emitted by
   `kaliv_bodyrig_digital_twin_m6_qualifier.py`. The qualifier validates
   BodyRig's canonical `bodyrig-digital-twin-release` v1 authority, recomputes
   its content-bound `dtrelease-...` id, requires
   `digital_twin_ready=true` and BodyRig's own
   `production_activation=true`, and binds `bodyrig_revision` to the pinned
   `Ternedal/BodyRig` SHA. ModelRig does **not** inherit that activation:
   the qualifier verdict and system release verdict remain
   `production_activation=false`.
6. `bodyrig_android_live_body` — the standalone Kaliv Body Android surface has
   passed its independent exact-head physical gate: authenticated RigLink,
   digest-bound active avatar, live BodyRig frames, ARCore runtime, detected-plane
   placement and explicit human visual acceptance are all evidence-bound. A PASS
   must reference the independent gate's content-addressed
   `kaliv-body-android-physical-gate:<modelrig-sha>:<sha256>` evidence ref.
   The embedded ModelRig SHA must either equal the pinned release revision
   directly, or be its Git ancestor **and resolve to the exact same Git tree**.
   The latter permits only a clean merge-commit identity change; any content
   change, squash/rewrite without ancestry, mutable label or path fails closed.
   The Android gate result must still report `production_activation=false`.
7. `end_to_end_latency` — one correlated real event traverses perception,
   cognition and outward voice/body behavior with measured latency evidence.
   A PASS must contain exactly one canonical
   `kaliv-end-to-end-latency:<modelrig-sha>:<sha256>` reference emitted by
   `kaliv_end_to_end_latency_qualifier.py`. The qualifier uses one monotonic
   observer clock, rejects simulated/cross-event evidence, and records measured
   phase/total latency with `threshold_applied=false` until a physical baseline
   establishes a defensible SLO. The embedded ModelRig SHA follows the same
   ancestor + exact-tree clean-merge rule as other ModelRig-bound evidence.
8. `recovery_soak` — the pinned system passes the agreed restart/recovery and
   long-running soak campaign. A PASS must contain exactly one canonical
   `kaliv-recovery-soak:<modelrig-sha>:<sha256>` reference emitted by the
   recovery-soak qualifier. The embedded ModelRig SHA must equal the pinned
   revision or be its ancestor with the exact same Git tree, permitting only a
   clean merge-commit identity change.
9. `repository_authority` — the repositories used for the release are protected
   by the accepted exact-green merge authority. A PASS must contain exactly one
   canonical
   `kaliv-repository-authority:<modelrig-sha>:<bodyrig-sha>:<visionrig-sha>:<voicerig-sha>:<sha256>`
   reference emitted from reviewed live repository-authority verifier outputs.
   All four embedded revisions must exactly match the release manifest pins.

A missing or failed gate yields `BLOCKED`. A PASS without evidence is malformed,
not merely pending.

## Authority boundary

The gate intentionally cannot activate production. The manifest must contain:

```json
"production_activation": false
```

and the emitted verdict also keeps `production_activation=false` even when all
nine gates qualify. Final activation remains owned by the existing explicit
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
    "bodyrig_android_live_body": {"status": "PENDING", "evidence_refs": []},
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

Exit code 0 means all nine evidence gates qualify. Exit code 1 means a valid
manifest is still blocked. Exit code 2 means the manifest itself is invalid.
