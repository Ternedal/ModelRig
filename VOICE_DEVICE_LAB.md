# Kaliv voice device lab — isolated physical acceptance (2026-10-15)

## Purpose and status

This **validation branch** combines:
- #2199 (Windows physical voice streaming/cancellation, 8/8 cleanup probes and 20/20 baseline turns);
- #2200 (Android Stop + barge-in cancel the actual OkHttp voice stream);
- backend proxy cancellation regression test;
- an opt-in isolated stack launcher and separate `a425f` Android package.

Do **not** run `scripts/start-dev-appliance.ps1` for this campaign. It stops release services. Do **not** merge this branch before required CI and phone tests.

| Component | Lab | Existing installation |
|---|---|---|
| Worker | 127.0.0.1:8121 | 8099 untouched; 8101 and prior ephemeral workers untouched |
| Go backend | 8181; `0.0.0.0` **only when explicitly passing `-ExposeLan`** | 8080 untouched |
| Device store | `validation/voice-device-lab/device-pairings.json` | Production pairing/credentials untouched |
| Android package | `dk.ternedal.modelrig.a425f` | Normal Kaliv package untouched |
| LLM | Existing local Ollama on 127.0.0.1:11434, read/use only | Existing Ollama kept running |

The backend only exposes authenticated routes to paired clients. With `MODELRIG_ADMIN_KEY` empty, the Go server explicitly restricts issuance of new pairing codes to a loopback caller. A remote phone **can redeem** a code, but cannot mint one. Stop the test consoles promptly after device testing; ordinary LAN HTTP is unencrypted, so use a trusted private network (or a separately secured Tailscale setup). No firewall rules are added by this script.

## Prepare

From PowerShell 7 on the rig, in the isolated checkout:

```powershell
Set-Location "C:\Rig\validation\ModelRig-voice-candidate"
git diff --quiet
if ($LASTEXITCODE -ne 0) { throw "Tracked changes present — do not overwrite" }
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { throw "Staged changes present — do not overwrite" }
git fetch origin validation/kaliv-voice-device-integration-20261015
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
git switch --detach origin/validation/kaliv-voice-device-integration-20261015
if ($LASTEXITCODE -ne 0) { throw "Checkout failed" }
pwsh -NoProfile -File .\scripts\voice-device-lab.ps1 -Role Start -ExposeLan
```

This builds the backend with an isolated output path, runs its Go proxy contract test, and starts **two dedicated PowerShell consoles** for the lab. It refuses occupied lab ports instead of killing unrelated processes. If Windows firewall denies the backend's new port, configure a narrowly scoped private-network rule manually; do not open arbitrary production ports.

Then in a *third* PowerShell console from the same checkout:

```powershell
pwsh -NoProfile -File .\scripts\voice-device-lab.ps1 -Role Pair
pwsh -NoProfile -File .\scripts\voice-device-lab.ps1 -Role BuildApk
```

The first command prints a **test-only** pairing code issued by the isolated backend. The second uses `gh` and the existing `a425f-apk.yml` GitHub Actions workflow to build and download an exact-HEAD signed test APK **without Android SDK on the rig**. (`gh auth login` must already be configured.) Only if `gh` is unavailable does it try the local SDK/Gradle route. The command prints the actual APK path. Install it using Android Studio or `adb install -r` on the connected test phone. Do not uninstall the normal Kaliv app or reuse its pairing token. In the `.a425f` app, pair against `http://<rig-private-ip>:8181` and enter the new test pairing code.

## Physical acceptance on the device

1. **Microphone**: grant microphone permission in the isolated app, select *Rig*, hold/tap to record a short Danish question. Confirm transcript arrives before the audio reply and that the reply is audible.
2. **Streaming**: ask a question that elicits several sentences. Observe first audio before the full answer. Confirm each sentence plays once, in order, without missing chunks.
3. **Stop during network streaming**: tap Stop *after the first audio chunk but while more text/audio is being generated*. Audio must cease and the overlay must become ready promptly; no late sentence may play.
4. **Rapid next turn**: immediately record another utterance. No old audio may resume and the new turn must complete normally.
5. **Barge-in**: opt in explicitly; test first with a headset. Speak while Kaliv is talking, verify cancellation, then only test speakerphone if device AEC is available and the RMS threshold is calibrated. Do not claim device barge-in works unless observed.
6. **Persistence**: complete a normal voice turn, close/reopen its conversation, confirm user transcript and complete assistant response are persisted.

Test **separately** that worker `8121` has no new `kaliv_voice_stream_` directories remaining after interrupted turns (do not delete historical evidence from prior runs).

## Recording the result

Record device model, Android version, candidate SHA, the paired test backend port, whether each of the six checks passed, any error details, and a short note on audio quality and observed stop delay. Avoid committing voice recordings, pairing credentials, secrets, or local reports to GitHub.

## Shut down safely

Close **only** the two dedicated lab console windows labelled voice worker/backend. This script intentionally has **no process-killing Stop action** because Windows venv launchers and Uvicorn have separate PIDs. Verify:

```powershell
pwsh -NoProfile -File .\scripts\voice-device-lab.ps1 -Role Status
```

The production services on 8080/8099 and normal Kaliv Android installation have not been touched by this lab. The separate `validation/voice-device-lab` pairing store persists locally for later test continuity.
