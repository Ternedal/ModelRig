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

All ten gates must be `PASS`, and every PASS must carry at least one explicit
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
4. `voicerig_physical_acceptance` — VoiceRig's final physical release acceptance
   has passed on the exact pinned VoiceRig revision using real source clips,
   CUDA-backed synthesis, explicit human listening QA, authenticated ModelRig
   provider verification, Piper fallback and VoiceRig restore. A PASS must carry
   exactly one canonical
   `voicerig-physical-acceptance:<voicerig-sha>:<sha256>` reference emitted by
   `kaliv_voicerig_physical_qualifier.py`. The embedded VoiceRig SHA must equal
   the pinned `Ternedal/VoiceRig` revision. CI or software exact-green alone is
   insufficient.

5. `bodyrig_photoreal_likeness` — the real-person Photoreal likeness gate,
   including required human review, has passed all the way through BodyRig's
   final Photoreal M6 authority. A PASS must contain exactly one canonical
   `bodyrig-photoreal-likeness:<bodyrig-sha>:<sha256>` reference emitted by
   `kaliv_bodyrig_photoreal_qualifier.py`. The qualifier accepts only
   `bodyrig-digital-twin-photoreal-release` v1 with
   `visual_authority=photoreal-v2-p3`,
   `canonical_digital_twin_ready=true`,
   `photoreal_digital_twin_ready=true`, a recomputed
   `dtphotorel-...` release id, and the exact pinned BodyRig revision.
   BodyRig's final authority is production-activating inside BodyRig, but
   ModelRig's qualifier and system-release verdict remain
   `production_activation=false`.
6. `bodyrig_digital_twin_m6` — one coherent Person lineage reaches canonical M6
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
7. `bodyrig_android_live_body` — the standalone Kaliv Body Android surface has
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
8. `end_to_end_latency` — one correlated real event traverses perception,
   cognition and outward voice/body behavior with measured latency evidence.
   A PASS must contain exactly one canonical
   `kaliv-end-to-end-latency:<modelrig-sha>:<sha256>` reference emitted by
   `kaliv_end_to_end_latency_qualifier.py`. The qualifier uses one monotonic
   observer clock, rejects simulated/cross-event evidence, and records measured
   phase/total latency with `threshold_applied=false` until a physical baseline
   establishes a defensible SLO. The embedded ModelRig SHA follows the same
   ancestor + exact-tree clean-merge rule as other ModelRig-bound evidence.
9. `recovery_soak` — the pinned system passes the agreed restart/recovery and
   long-running soak campaign. A PASS must contain exactly one canonical
   `kaliv-recovery-soak:<modelrig-sha>:<sha256>` reference emitted by the
   recovery-soak qualifier. The qualifier must be given the actual Stage-B final
   report with `--stage-b-report`; it SHA-256-binds the exact report bytes,
   requires `status=complete`, all recorded Stage-B command exit codes to
   be zero, `summary.total=9` with an empty `summary.errors`, all final/strict
   physical gates PASS, `production_activation=false`, a clean candidate
   checkout, and the same candidate Git SHA as the recovery observations.
   It also requires the Stage-B report's exact four component receipts
   (`strict_stage_b`, `updater_chain`, `physical_campaign`,
   `component_final_gate`), resolves their repository-relative paths under
   `--repository-root`, and verifies file size, SHA-256, embedded schema,
   full candidate identity, gate state, and the canonical eight-/nine-proof
   summaries. Receipt booleans are not sufficient: the qualifier re-runs the
   canonical strict/updater evaluators against the lifecycle source and logs,
   re-runs all eight campaign evidence validators against their source
   artifacts, and re-runs the final browser/campaign validator against the
   physical attestation and underlying browser receipt. The stored receipt must
   remain consistent with that independent revalidation.
   A caller-supplied label, a recomputed hash over a handcrafted top-level
   Stage-B report, or an unverified Stage-B path is not sufficient. The embedded ModelRig SHA must
   equal the pinned revision or be its ancestor with the exact same Git tree,
   permitting only a clean merge-commit identity change.
10. `repository_authority` — the repositories used for the release are protected
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
    "voicerig_physical_acceptance": {"status": "PENDING", "evidence_refs": []},
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

## Assemble a fully-qualified manifest

When all ten canonical evidence refs already exist, do not hand-edit the JSON
shape. `scripts/kaliv_release_manifest_assembler.py` creates the manifest and
immediately submits the in-memory result to the same
`kaliv_system_release_gate.evaluate_manifest(...)` authority before writing it.

The assembler **does not create evidence**, downgrade a missing gate to pending,
or activate production. All ten refs and all four immutable repository SHAs are
required.

```powershell
python scripts/kaliv_release_manifest_assembler.py `
  --release-id kaliv-rc-1 `
  --modelrig-sha <40-hex> `
  --bodyrig-sha <40-hex> `
  --visionrig-sha <40-hex> `
  --voicerig-sha <40-hex> `
  --software-exact-green-ref <canonical-ref> `
  --consciousness-live-lifecycle-ref <canonical-ref> `
  --visionrig-physical-perception-ref <canonical-ref> `
  --voicerig-physical-acceptance-ref <canonical-ref> `
  --bodyrig-photoreal-likeness-ref <canonical-ref> `
  --bodyrig-digital-twin-m6-ref <canonical-ref> `
  --bodyrig-android-live-body-ref <canonical-ref> `
  --end-to-end-latency-ref <canonical-ref> `
  --recovery-soak-ref <canonical-ref> `
  --repository-authority-ref <canonical-ref> `
  --manifest .\validation\kaliv-release-manifest.json `
  --verdict .\validation\kaliv-release-verdict.json
```

A successful assembler run means only that the exact supplied evidence refs form
a `QUALIFIED`, `release_ready=true` manifest under the existing final gate.
Both the manifest and verdict retain `production_activation=false`.

## Evaluate a manifest directly

```powershell
python scripts/kaliv_system_release_gate.py .\path\to\kaliv-release-manifest.json
```

Exit code 0 means all ten evidence gates qualify. Exit code 1 means a valid
manifest is still blocked. Exit code 2 means the manifest itself is invalid.

## Binding qualified Consciousness evidence

Do not mark the `consciousness_live_lifecycle` gate PASS by hand. Once
`scripts/consciousness_live_lifecycle_qualifier.py` has produced a QUALIFIED
verdict for the exact pinned ModelRig SHA, bind it into the release manifest with:

```powershell
python scripts/kaliv_system_release_bind_consciousness.py \
  .\kaliv-release-manifest.json \
  .\consciousness-live-lifecycle-verdict.json \
  --output .\kaliv-release-manifest.bound.json
```

The binder validates the exact ModelRig SHA, all lifecycle qualification flags,
the release evidence reference shape, and all no-authority / `production_activation=false`
constraints. It may change only the `consciousness_live_lifecycle` gate. An explicit
FAIL is never overwritten, and an existing PASS is accepted only when it already
references the exact same qualified evidence.
