# Kaliv V1 rig smoke — read-only readiness

This is a diagnostic, NOT physical acceptance, software requalification,
or a release receipt. The tool verifies exact clean ModelRig Git checkout,
live backend/worker health and running ASR/TTS availability over loopback.
It does not load a model, transcribe audio, start a service, install packages,
read tokens, or alter evidence.

Run from a clean ModelRig checkout on the Windows rig:

    git rev-parse HEAD
    git status --short
    $head = (git rev-parse HEAD).Trim()
    python scripts\kaliv_v1_rig_smoke.py --expected-modelrig-sha $head

The script emits structured JSON to stdout, with exit 0 only if checkout,
backend, worker, ASR and TTS status are ready. Optional --backend-url and
--worker-url accept only plain HTTP loopback hosts and explicit ports.
Existing scripts/voice_runtime_preflight.py diagnoses the interpreter;
scripts/rig_preflight.py performs full Agent 3/Ollama environment preflight;
scripts/voice_baseline.py performs real Danish WAV validation.

Every physical_gates result remains NOT_TESTED, including VoiceRig CUDA and
human listening, VisionRig camera, BodyRig held-out likeness, Android/Quest,
consciousness recovery, latency, soak and repository authority. Both
release_gate_satisfied and production_activation remain false.

**Freeze boundary:** this implementation is isolated on a draft PR. Do not
merge into qualified V1 main until explicitly re-frozen and requalified.
