# Voice runtime preflight — read-only V1 blocker aid

The core worker does **not** bundle faster-whisper or piper-tts. Installing
packages in a different Python virtualenv does not fix the running worker.
This diagnostic queries the **actual running worker** and separately checks
the interpreter used to run the diagnostic. It never loads a voice model.

## Windows rig

From the ModelRig checkout, use the interpreter that actually starts worker:

```powershell
$workerPython = "C:\path\to\actual\worker\venv\Scripts\python.exe"
& $workerPython scripts\voice_runtime_preflight.py --json
```

Default worker URL: http://127.0.0.1:8099 (loopback only). The script reads
GET /voice/asr/status and GET /voice/tts/status, never changes settings.
Running-worker availability, not a package installed in an unrelated Python,
is the authority. VoiceRig may provide TTS even without a local Piper import.

If ASR is unavailable in both interpreter and worker, install into the
**verified worker virtualenv**:

```powershell
& $workerPython -m pip install faster-whisper
& $workerPython -m pip show faster-whisper
```

If Piper fallback is selected but not installed:

```powershell
& $workerPython -m pip install piper-tts
```

Check which Python PID listens on 8099 before restarting **only** the worker
through the existing appliance procedure. Do not kill every Python process
or mutate a frozen checkout. Re-run the preflight after restart.

A passing preflight means only that the running worker reports the
dependencies as available. It does **not** prove CUDA/model-load readiness,
Danish transcription quality, real audio playback, or VoiceRig release acceptance.
Continue with real WAV tests and VOICE_BASELINE.md.

Safety: every output explicitly reports release_gate_satisfied=false and
production_activation=false. No evidence receipt or tag is generated.

## CI contract test

```powershell
& $workerPython tests\workflow_voice_runtime_preflight.py
```

CI's normal tests/workflow_*.py discovery runs this test without a rig.
