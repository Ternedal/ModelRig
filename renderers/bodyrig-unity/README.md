# BodyRig Unity/VRM renderer

This is the concrete renderer adapter for BodyRig. It consumes the landed
renderer-neutral `bodyrig.render_frame` v0.1 wire contract and owns
Unity/VRM-specific bones, expressions and retargeting.

The deterministic fixture renderer was physically proved on the Windows rig on
6 September 2026 and that result is recorded by #903. **PR #846 is the current
product-path proof:** the same renderer must now consume the real ModelRig
`/api/v1/body/frames` stream and visibly follow a real conversation. It remains
draft until the live machine gate, direct visual acceptance and independent
final gate all pass on the same exact remote PR-head.

`production_activation=false` throughout.

## Pinned baseline

- Unity: `6000.3.21f1` (Unity 6.3 LTS)
- UniVRM: `v0.131.2`
- VRM format: VRM 1.0
- UPM packages: `com.vrmc.gltf` + `com.vrmc.vrm`

The package manifest pins UniVRM by tag and package path. Do not replace these
pins with floating Git branches.

## Renderer boundary

`BodyRigRenderFrame` -> Unity/VRM:

- `blink` -> VRM `blink`
- approximate VoiceRig `audio_envelope` -> VRM `aa` mouth opening
- timed canonical `aa/ih/ou/ee/oh` -> corresponding VRM presets
- semantic emotions -> VRM `happy/angry/sad/relaxed/surprised`
- `gaze_target=user|camera` + renderer-neutral gaze strength -> humanoid head/eye aiming
- procedural head yaw/pitch hints -> humanoid head rotation
- `breath` + `energy` -> subtle humanoid chest rotation
- semantic `gesture` -> optional Animator trigger mapping through `BodyRigGestureRouter`
- `gesture=explain` -> conservative procedural humanoid-arm fallback without authored animation

The v0.1 wire retains all current M2.2/M2.3 renderer-neutral personalization
metadata. The renderer deliberately does **not** reinterpret
`resolved_gesture=bodyprint:*` as an Animator clip or `.vrma` path.
BodyRig/ModelRig never sends `HumanBodyBones`, Unity object paths or VRM
expression keys.

## Interruption rule

Mouth/viseme output is applied only while `state == speaking`. `interrupted`,
`listening`, `thinking`, `idle` or error clears mouth presets. `interrupted` and
`error` also cancel both authored and procedural gesture paths, and the
procedural driver restores captured arm baselines immediately.

## M2.7 current-profile -> renderer preparation

Install/select the `.mrbody` profile through landed M2.6/M2.7 APIs, then prepare
it through landed M2.8:

```powershell
$handoff = python scripts/bodyrig_prepare_renderer_profile.py C:\path\to\bodyrig-profiles | ConvertFrom-Json
$env:BODYRIG_VRM_PATH = $handoff.BODYRIG_VRM_PATH
$handoff
```

The staged path is content-addressed by canonical body id + exact selected
`.mrbody` SHA-256, and only validated `avatar.vrm` is materialized. Same-bodyid
package replacement remains stale until explicit re-selection.

## Deterministic fixture baseline

`Assets/BodyRig/Resources/bodyrig-demo.json` covers idle, listening, thinking,
`audio_envelope` speaking with `explain`, timed-viseme speaking, interruption,
listening recovery and idle. The fixture clock starts only after asynchronous
VRM binding completes.

The fixture path was the M0.3 renderer proof and is now a regression baseline.
With live-rig variables absent, `BodyRigDemoBootstrap` still runs this exact
path.

## Live frames from the rig — #846 product path

`BodyRigFrameSource` opens `GET <rig>/api/v1/body/frames` as server-sent events
behind the paired device Bearer token. Each accepted frame passes through the
same `BodyRigVrmRenderer.Apply` as the fixture player.

The live source is fail-closed around the renderer boundary:

- every frame is wire-validated before apply;
- no frame reaches the avatar before asynchronous VRM bind is complete;
- timestamps must be strictly increasing inside one HTTP/SSE stream;
- reconnect starts a new timestamp authority instead of guessing from clock
  rewinds;
- disconnect, rig restart and 404/no-active-body reconnect after a bounded
  pause instead of killing the renderer;
- the Unity process can emit a live receipt only **after** a validated frame was
  actually applied to a bound renderer;
- the token is never serialized into evidence.

The bootstrap selects live mode only when both variables are set:

```text
BODYRIG_RIG_URL=http://127.0.0.1:8080
BODYRIG_RIG_TOKEN=<paired device token in process environment>
```

### Known pre-existing Slice-B wire debt

Issue #904 tracks a mismatch already present on `main`: Slice B appends
`session_id` and `body_id` beside the canonical v0.1 frame although the schema
is `additionalProperties: false`. The #846 preflight records and strips exactly
those two known metadata keys before canonical parsing. Every other unknown
top-level field still fails closed. #904 will move the metadata out of the
canonical payload instead of silently widening this PR.

## Authoritative #846 physical live proof

Run only on the physical Windows rig from a fully clean checkout whose local
HEAD equals the freshly fetched `origin/feat/unity-frame-source` and is not
behind current `origin/main`. The launcher checks that authority itself and
invalidates the run if either remote ref moves while evidence is being
collected.

Keep the already paired device token in the process environment. Do **not** put
it on a command line, in an issue or in an evidence file.

### 1. Machine gate: preflight + Unity build/load + actual live frame

```powershell
cd C:\Users\admin\Desktop\modelrig-git
git fetch origin
git switch feat/unity-frame-source
git pull --ff-only origin feat/unity-frame-source

.\scripts\bodyrig_unity_live_physical_proof.ps1 `
  -Store $env:KALIV_BODY_STORE `
  -RigUrl "http://127.0.0.1:8080"
```

If the store is not exposed through `KALIV_BODY_STORE`, pass its real path to
`-Store` instead. Do not invent a replacement store merely to make the gate
pass.

The live launcher reuses the physically proven batch-build substrate and invokes
the exact Unity entrypoint
`ModelRig.BodyRig.UnityRenderer.Editor.BodyRigBuild.BuildWindows` before it
launches the resulting player.

The machine gate writes evidence outside the repository under
`%LOCALAPPDATA%\ModelRig\BodyRigLiveEvidence\<exact-sha>\` by default:

- `live-preflight-receipt.json` — exact active body/package, authenticated
  bounded SSE, strict timestamp order, canonical frame validation;
- `renderer/build-receipt.json` — pinned Unity build + artifact hashes;
- `renderer/runtime-receipt.json` — real VRM load + renderer bind;
- `unity-live-receipt.json` — Unity itself observed Bearer live mode and wrote
  the receipt only after `renderer.Apply(frame)`;
- `live-run-receipt.json` — SHA-256 binds the machine evidence to PR #846,
  exact remote candidate, body, package and rig URL.

A successful machine phase prints:

```text
BODYRIG UNITY LIVE MACHINE GATE: PASS
```

That is **not** visual acceptance and is not enough to merge.

### 2. Directly observe a real ModelRig conversation

Leave the renderer open and use ModelRig/Kaliv normally. Confirm directly that:

- `idle`, `listening`, `thinking`, `speaking`, `interrupted` are visibly
  distinct during the real turn;
- gaze, blink and breath remain alive;
- mouth motion follows the live speech playback rather than a canned fixture;
- interruption immediately neutralizes mouth and active gesture.

Only after all four are genuinely observed, record the separate human receipt:

```powershell
.\scripts\bodyrig_unity_live_visual_acceptance.ps1 `
  -EvidenceDir "<path printed by the machine gate>" `
  -StatesDistinct `
  -GazeBlinkBreathVisible `
  -SpeechMouthTracksPlayback `
  -InterruptionImmediateNeutral
```

There is no partial acceptance. The script binds the human attestation to the
machine receipts, candidate/body/package and operator machine.

### 3. Independent final gate

The visual-acceptance command prints the exact final command. Its form is:

```powershell
$sha = git rev-parse HEAD
python scripts/bodyrig_unity_live_physical_gate.py `
  --expected-sha $sha `
  --evidence-dir "<same evidence directory>"
```

The independent gate re-reads and re-hashes the full evidence chain, including
the built executable, Unity log and runtime receipt. It rejects stale candidate
identity, tampered receipts, missing machine-live proof, incomplete visual
acceptance, path substitution and any `production_activation=true` claim.

The only accepted terminal result is:

```text
BODYRIG UNITY LIVE PHYSICAL GATE: PASS — #846 @ <exact-sha> ...
production_activation=false
```

Even that PASS does not merge the PR automatically. Re-check current PR/main
authority before landing.

## Fixture physical proof — historical baseline

The older scripts below are retained because they produced and independently
validated the physical fixture renderer proof now documented by #903:

- `scripts/bodyrig_unity_physical_proof.ps1`
- `scripts/bodyrig_unity_visual_acceptance.ps1`
- `scripts/bodyrig_unity_physical_gate.py`

They intentionally retain the historical #720 evidence schema and are **not**
the acceptance path for #846. The #846 live launcher reuses the already proven
build/runtime substrate internally, then adds its own network/live evidence and
separate visual gate.

## Android host: the Kaliv Body app

Host choice taken 4/9 (reversible): a standalone Unity build of this project,
package name **`dk.ternedal.kalivbody`**. Kaliv's ⋮ → **Krop** launches exactly
that package and hands it the rig address and Kaliv's own device token as
intent extras (`bodyrig_rig_url`, `bodyrig_rig_token`), which `BodyRigRigLink`
reads first — so the body app never pairs on its own. Unity as a Library inside
Kaliv stays the V2 path if one app is wanted; everything below the host is
identical. Set the package name in Player Settings → Android.

## Manual development run

For renderer development only:

```powershell
$handoff = python scripts/bodyrig_prepare_renderer_profile.py C:\path\to\bodyrig-profiles | ConvertFrom-Json
$env:BODYRIG_VRM_PATH = $handoff.BODYRIG_VRM_PATH
& "C:\Program Files\Unity\Hub\Editor\6000.3.21f1\Editor\Unity.exe" `
  -projectPath "$PWD\renderers\bodyrig-unity"
```

A manually supplied VRM path is acceptable for development but is not physical
acceptance evidence.

## Deliberate boundaries

Still separate from #846:

- body/avatar likeness fidelity
- full person-specific semantic `.vrma` interpretation
- final Android/Quest product packaging
- spatial `object:*` / `world:*` target registry
- shipped person-specific gesture animation library
- production activation

`production_activation=false` remains authoritative until a separate production
gate says otherwise.
