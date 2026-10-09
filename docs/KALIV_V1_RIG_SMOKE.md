# Kaliv V1 rig smoke — read-only readiness

This is a diagnostic, NOT physical acceptance, software requalification,
or a release receipt. The tool verifies exact clean ModelRig Git checkout,
live backend/worker health and running ASR/TTS availability over loopback.
It does not load a model, transcribe audio, start a service, install packages,
read tokens, or alter evidence.

Run from a clean ModelRig checkout on the Windows rig. **First** obtain the
independently reviewed exact ModelRig SHA from the approved V1 software-evidence
record or release candidate manifest (not from the checkout under inspection).
A SHA copied from `git rev-parse HEAD` cannot prove the checkout is the right
release candidate: even a stale/unauthorized clean checkout would self-match.

    # Paste the independent 40-hex ModelRig SHA from reviewed release evidence:
    $expectedModelRigSha = 'REPLACE_WITH_REVIEWED_40_HEX_MODELRIG_SHA'
    git rev-parse HEAD
    git --no-optional-locks status --short
    python scripts\kaliv_v1_rig_smoke.py --expected-modelrig-sha $expectedModelRigSha

The placeholder MUST be replaced with the lower-case SHA approved for the
candidate currently under test. Never generate this expected value with
`git rev-parse HEAD`, `git branch`, a mutable tag, or the running service.
A draft-branch checkout will correctly fail the exact-V1-source check; this
tool is not part of the software-qualified frozen V1 tree and cannot be treated
as a V1 release receipt without an independently authorized re-freeze.

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
