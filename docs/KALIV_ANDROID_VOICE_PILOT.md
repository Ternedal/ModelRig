# Kaliv Android voice pilot — isolated physical acceptance

This is **not** a production release or an APK update. It is the next safe step
after the physical voice acceptance on 2026-10-15.

## Already proven on the physical rig

- Frozen Windows worker SHA: e01b2d1c989f4da1d454e004f074870741f409df
- Whisper large-v3 on CUDA, automatic cuBLAS/cuDNN discovery, Danish Piper TTS.
- POST /voice/converse/stream returned NDJSON transcript, chunk, done events
  using local Ollama qwen2.5-coder:7b.
- Operator decoded and **heard** the returned WAV audio.
- The earlier PowerShell failure was caused by treating a byte-array response
  as JSON objects. It was not an ASR/worker failure.

## What this pilot adds

1. GitHub Actions builds a signed APK with **separate Android package**
   dk.ternedal.modelrig.a425f. It installs alongside the normal Kaliv app and
   uses its own preferences and pairing token; it does not replace the app.
2. PowerShell starts the **same verified frozen worker** on loopback port 18121
   and a separate ModelRig backend on a private LAN IPv4, port 18180.
3. The backend gets a fresh temporary pairing database and ephemeral admin
   key. Neither the normal worker 8099, backend 8080, their tokens, nor Task
   Scheduler are modified.
4. Before phone testing, the script validates the worker SHA/checksum,
   backend version 2.0.15, pairing/auth, voice status and a complete
   authenticated POST /api/v1/voice/converse/stream through the backend.
   It decodes NDJSON bytes correctly and saves a WAV.
5. It then prints a short-lived pairing code and URL for the test app.
   Press R to regenerate an expired code; Enter stops both test processes.

## Build and install the separate APK

- Open the kaliv-voice-android-pilot GitHub Actions run for this branch.
- Wait for **side-by-side-apk** and **pilot-script-syntax** to pass.
- Download artifact kaliv-voice-test-(commit) ZIP on the phone, extract
  kaliv-voice-test.apk, tap it and confirm the Android installation prompt.
- Open the newly installed test app from Android's installation screen.
  The original Kaliv remains installed. No USB or ADB is needed.
- Do not publish the artifact as a release or feed it to the updater.

## Run the isolated stack on the Windows rig

The rig already has GitHub CLI authenticated. Fetch only the script into a
test directory. **Do not switch the existing ModelRig checkout or update main.**

PowerShell 7:

    New-Item -ItemType Directory -Force C:\Rig\test\kaliv-android-voice-pilot | Out-Null
    gh api -H "Accept: application/vnd.github.raw+json" "repos/Ternedal/ModelRig/contents/scripts/kaliv-android-voice-pilot.ps1?ref=work/kaliv-android-voice-pilot-20261015" | Set-Content -Encoding utf8 C:\Rig\test\kaliv-android-voice-pilot\run.ps1
    & C:\Rig\test\kaliv-android-voice-pilot\run.ps1

If the backend executable cannot be found automatically, download the
separate Actions artifact kaliv-voice-pilot-backend-(commit) ZIP and extract
modelrig-server-pilot.exe and SHA256SUMS.txt together into
C:\Rig\test\kaliv-android-voice-pilot. The script finds that executable
automatically and verifies its SHA-256. Alternatively pass
-BackendExe "C:\path\to\modelrig-server-windows-x64.exe". The script verifies
the running backend version is 2.0.15 and fails closed otherwise.

If more than one suitable LAN IP is found, pass -LanIp "192.168.x.y" with the
rig's actual private Wi-Fi/Ethernet IPv4. The script does **not** change Windows
Firewall rules. If the phone cannot reach port 18180, inspect the firewall and
network profile before changing anything. Use a trusted private network only.

The script blocks until the operator ends the session, then terminates only
its own two child processes, restores process environment variables and
removes the temporary pairing database. Logs and probe WAV remain under
C:\Rig\test\kaliv-android-voice-pilot.

## Android acceptance

1. In the **test app**, pair to the URL and code printed by PowerShell.
   Do not enter the production port 8080 URL.
2. Grant microphone permission when Android asks.
3. Tap the microphone, say "Hvor meget er to plus to?" and finish recording.
4. Require all: visible Danish transcript, text reply, **audible** reply,
   no 401/502/503 and a second successful voice turn.
5. End the PowerShell pilot with Enter. The test app's temporary token stops
   working as expected; the original Kaliv remains paired to production.

This is a **physical phone test**. CI and the backend proxy probe do not
substitute for it. Do not claim Android acceptance until the operator has
actually heard the reply from the phone.

## Independent gates still outstanding

- exact-head-qualification on the frozen worker PR #2202.
- Production worker promotion/rollback on port 8099.
- Main branch protection, signed release, updater and Piper GPL distribution
  review. The pilot must not bypass any of these gates.
