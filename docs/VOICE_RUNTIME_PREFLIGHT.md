# Voice runtime preflight — read-only V1 blocker aid

The core worker does **not** bundle faster-whisper or piper-tts. Installing
packages in a different Python virtualenv does not fix the running worker.
This diagnostic queries the **actual running worker** and separately checks
the interpreter used to run the diagnostic. It never loads a voice model.

## Windows rig

From the ModelRig checkout, first identify the **actual** process listening
on the worker port. Running a diagnostic with another Python is not proof of
which packages the worker can import:

```powershell
$listener = Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction Stop | Select-Object -First 1
$workerProc = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
$workerProc | Select-Object ProcessId, Name, ExecutablePath, CommandLine | Format-List
```

Use `ExecutablePath` and the process command line to verify the worker's
Python virtualenv. If the executable path is missing or the listener is a
launcher rather than the worker, inspect the child process/command line.
Do not guess the interpreter.

The preflight is safe to run with any Python, but it marks that interpreter as
**inspected** rather than **verified as the worker's**:

```powershell
$diagnosticPython = "C:\path\to\your\Python\python.exe"
& $diagnosticPython scripts\voice_runtime_preflight.py --json
```

Default URL: http://127.0.0.1:8099 (loopback only). The script independently
reads GET /voice/asr/status and GET /voice/tts/status, never changes settings,
does not follow HTTP redirects, and ignores HTTP proxy configuration.
HTTP failures and malformed responses are captured per endpoint.

**Important:** `find_spec()` only discovers module metadata. It does not
import `faster_whisper` / `piper`, resolve native DLL dependencies, or load a model.
A discovered module does not mean it imports correctly. The actual running
worker's endpoint is the source of truth, and VoiceRig may provide TTS without
a local Piper package.

Only **after** verifying the actual worker's interpreter from the listening
process and confirming a genuinely missing dependency in its logs/status
should an operator choose to install:

```powershell
# Set this path only after matching it to the actual worker process.
$verifiedWorkerPython = "C:\verified\worker-venv\Scripts\python.exe"
& $verifiedWorkerPython -m pip install faster-whisper
& $verifiedWorkerPython -m pip show faster-whisper

# Only if the SELECTED TTS provider is Piper and it is truly missing:
# & $verifiedWorkerPython -m pip install piper-tts
```

A module whose metadata is present but whose import fails may have a broken
native dependency; inspect the worker logs before restarting or installing.
Restart **only** the verified worker using the existing appliance procedure
if needed. Do not kill every Python process or change the frozen checkout.
Re-run the preflight after restart.

A passing preflight means only that the running worker reports the
dependencies as available. It does **not** prove CUDA/model-load readiness,
Danish transcription quality, real audio playback, or VoiceRig release acceptance.
Continue with real WAV tests and VOICE_BASELINE.md.

Safety: every output explicitly reports release_gate_satisfied=false and
production_activation=false. No evidence receipt or tag is generated.

## CI contract test

```powershell
& $diagnosticPython tests\workflow_voice_runtime_preflight.py
```

CI's normal tests/workflow_*.py discovery runs this test without a rig.
