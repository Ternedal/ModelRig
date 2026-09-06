# BodyRig Unity/VRM renderer proof

This is the first concrete renderer adapter for BodyRig. It consumes the landed renderer-neutral `bodyrig.render_frame` v0.1 wire contract and owns Unity/VRM-specific bones, expressions and retargeting.

M2.8 renderer-neutral wire + digest-bound current-profile handoff is already on `main`. This draft contains only the Unity/VRM proof layer and must remain draft until a physical Windows build, a machine-confirmed real selected VRM load/bind, and explicit visual acceptance have all been recorded against the same exact draft SHA.

## Pinned baseline

- Unity: `6000.3.21f1` (Unity 6.3 LTS)
- UniVRM: `v0.131.2`
- VRM format: VRM 1.0
- UPM packages: `com.vrmc.gltf` + `com.vrmc.vrm`

The package manifest pins UniVRM by tag and package path. Do not replace these pins with floating Git branches.

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

The v0.1 wire retains all current M2.2/M2.3 renderer-neutral personalization metadata. The draft deliberately does **not** reinterpret `resolved_gesture=bodyprint:*` as an Animator clip or `.vrma` path. BodyRig/ModelRig never sends `HumanBodyBones`, Unity object paths or VRM expression keys.

## Interruption rule

Mouth/viseme output is applied only while `state == speaking`. `interrupted`, `listening`, `thinking`, `idle` or error clears mouth presets. `interrupted` and `error` also cancel both authored and procedural gesture paths, and the procedural driver restores captured arm baselines immediately.

## M2.7 current-profile -> renderer preparation

Install/select the `.mrbody` profile through landed M2.6/M2.7 APIs, then prepare it through landed M2.8:

```powershell
$handoff = python scripts/bodyrig_prepare_renderer_profile.py C:\path\to\bodyrig-profiles | ConvertFrom-Json
$env:BODYRIG_VRM_PATH = $handoff.BODYRIG_VRM_PATH
$handoff
```

The staged path is content-addressed by canonical body id + exact selected `.mrbody` SHA-256, and only validated `avatar.vrm` is materialized. Same-bodyid package replacement remains stale until explicit re-selection.

## Deterministic canned demo

`Assets/BodyRig/Resources/bodyrig-demo.json` covers idle, listening, thinking, `audio_envelope` speaking with `explain`, timed-viseme speaking, interruption, listening recovery and idle. The fixture clock starts only after asynchronous VRM binding completes.

## Live frames from the rig (product path)

The fixture is the proof. The product reads the rig: `BodyRigFrameSource`
opens `GET <rig>/api/v1/body/frames` (server-sent events, one v0.1 frame per
`data:` line, 20 fps) behind the device token and applies each frame through
the same `BodyRigVrmRenderer.Apply` the fixture player uses. Every frame is
validated first, none is applied before the VRM is bound, timestamps must
advance within a stream, and a dropped connection reconnects after a delay
instead of failing. The bootstrap picks it only when both are set:

    BODYRIG_RIG_URL=http://192.168.1.33:8080
    BODYRIG_RIG_TOKEN=<device token from pairing>

With either unset the bootstrap runs the fixture exactly as before, so the
physical proof is unchanged. The rig side (slices A and B of
`docs/bodyrig/UNITY_RENDERER_ROADMAP.md`) serves the active body's assets
and drives the frames from the chat: thinking, waiting for a tool, speaking
with the phone's actual playback timing, interrupted.

## Android host: the Kaliv Body app

Host choice taken 4/9 (reversible): a standalone Unity build of this project,
package name **`dk.ternedal.kalivbody`**. Kaliv's ⋮ → **Krop** launches exactly
that package and hands it the rig address and Kaliv's own device token as
intent extras (`bodyrig_rig_url`, `bodyrig_rig_token`), which `BodyRigRigLink`
reads first -- so the body app never pairs on its own. Unity as a Library
inside Kaliv stays the V2 path if one app is wanted; everything below the
host is identical. Set the package name in Player Settings → Android.

## Authoritative physical proof path

Run this only from the exact #720 draft candidate on the physical Windows rig with a genuinely selected M2.7 profile.

### Repository-state rule

The proof starts and ends with a **fully clean** `git status --porcelain=v1 --untracked-files=all`, not merely a clean tracked diff.

Only standard Unity ephemeral state is ignored:

- `Library/`
- `Temp/`
- `Obj/`
- `Logs/`
- `UserSettings/`
- local `Build/`

The deterministic proof scene is generated only for the batch build and removed in a `finally` block, including its newly-created scene directory/meta when applicable.

`Packages/packages-lock.json` is deliberately **not** ignored. If Unity creates or changes dependency-lock state, the proof stops as dirty. Do not delete/bypass that signal just to obtain a PASS; review whether the lock file must be pinned in the draft and rerun exact-head qualification first.

### 1. Build, launch, prove runtime VRM load/bind, hash and receipt

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bodyrig_unity_physical_proof.ps1 `
  -Store C:\path\to\bodyrig-profiles
```

The harness invokes the pinned Unity editor in batch mode through `ModelRig.BodyRig.UnityRenderer.Editor.BodyRigBuild.BuildWindows` before launching the resulting proof executable. The script fails closed unless:

- the checkout is fully clean before Unity starts;
- the draft is not behind freshly fetched `origin/main`;
- the selected `.mrbody` current binding freshly validates;
- the digest-bound staged avatar matches its SHA-256;
- Unity/UniVRM pins match the qualified draft;
- the installed Unity executable is `6000.3.21`;
- the Windows batch build succeeds and produces a non-empty executable;
- the generated scene is removed and the repository is still fully clean after build;
- `origin/main` does not move during the build;
- the built executable is launched with the **same** `BODYRIG_VRM_PATH` plus candidate/body/package/avatar identity bindings;
- the running renderer itself emits a runtime receipt only after `Vrm10.LoadPathAsync`, first-person setup, mesh display and `renderer.Bind(...)` have completed;
- the renderer-computed avatar SHA-256 matches the selected M2.8 handoff;
- the runtime receipt arrives before the bounded timeout and matches exact candidate/body/package/avatar/Unity identity;
- the repository remains fully clean and `origin/main` remains unchanged through runtime proof.

Build success is not runtime-load success. The build receipt is not authoritative for #717 unless `runtime_load_verified=true`.

By default evidence is kept outside the repository at:

```text
%LOCALAPPDATA%\ModelRig\BodyRigEvidence\<exact-draft-sha>\
```

The directory contains the built executable, Unity build log, `runtime-receipt.json` and `build-receipt.json`. The build receipt binds exact draft SHA, `origin/main` SHA, body id, package/avatar digests, Unity/UniVRM pins and SHA-256/byte counts for every evidence artifact. It explicitly keeps `visual_acceptance=false` and `production_activation=false`.

`-NoLaunch` is debugging only. It deliberately leaves runtime load and visual acceptance unproven.

### 2. Directly observe and attest every visual requirement

Watch a full deterministic cycle. Only after directly observing every required behavior, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bodyrig_unity_visual_acceptance.ps1 `
  -StatesDistinct `
  -GazeBlinkBreathVisible `
  -ExplainGestureVisible `
  -SpeechModesDiffer `
  -InterruptionImmediateNeutral
```

There is no partial or implicit acceptance. All five switches are required. Before writing `visual-receipt.json`, the script re-hashes the executable, staged avatar and runtime receipt and requires the runtime receipt to prove both VRM load and renderer bind. The visual receipt SHA-binds exact build receipt, runtime receipt, executable and profile identity.

### 3. Independent fail-closed gate

```powershell
$sha = git rev-parse HEAD
python scripts/bodyrig_unity_physical_gate.py --expected-sha $sha
```

A valid result ends with:

```text
BODYRIG UNITY PHYSICAL GATE: PASS
```

The independent gate re-hashes the executable, build log, runtime receipt and staged VRM; structurally re-validates VRM 1.0; checks project pins; requires exact draft SHA and fully clean repository state; requires machine-confirmed runtime `vrm_loaded=true` + `renderer_bound=true`; requires all five visual observations; and rejects any evidence that claims production activation.

A PASS is evidence for #717/#720 only. It is **not** production activation. Before any merge, re-read #731 and apply normal exact-head/freeze discipline. Any draft-head change invalidates the physical receipt and requires a fresh physical run.

## Manual development run

```powershell
$handoff = python scripts/bodyrig_prepare_renderer_profile.py C:\path\to\bodyrig-profiles | ConvertFrom-Json
$env:BODYRIG_VRM_PATH = $handoff.BODYRIG_VRM_PATH
& "C:\Program Files\Unity\Hub\Editor\6000.3.21f1\Editor\Unity.exe" `
  -projectPath "$PWD\renderers\bodyrig-unity"
```

A manually supplied VRM path is acceptable for renderer development but is not package-selection evidence.

## Deliberate boundaries

Still separate from this M0.3 gate:

- body/avatar likeness fidelity
- semantic `.vrma` interpretation
- Android embedding
- Quest/OpenXR packaging
- spatial `object:*` / `world:*` target registry
- shipped person-specific gesture animation library
- production activation

Issue #717 remains the physical renderer authority. `production_activation=false` remains authoritative until a separate production gate says otherwise.
