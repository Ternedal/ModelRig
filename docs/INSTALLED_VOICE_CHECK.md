# Installed v2.0.17 voice diagnostic

Use this on the Windows rig after the normal updater has installed
[v2.0.17](https://github.com/Ternedal/ModelRig/releases/tag/v2.0.17). It targets
that published release, not the version or HEAD of a source checkout.

Run the standalone `scripts/test-installed-voice.ps1` file locally on the rig:

```powershell
& .\test-installed-voice.ps1 -RigRoot 'C:\Rig\ModelRig'
```

The file needs Windows PowerShell 5.1 or PowerShell 7, already available Windows
components only. It needs neither Python, Android SDK, git, pairing credentials
nor administrator rights beyond permission to write the diagnostic directory.
Keep Kaliv idle while it runs. It does not restart processes, change voice
settings, activate agents or replace the published release. It calls the local
backend on port 8080 and worker on port 8099. Alternate ports are explicit
`-ServerPort` / `-WorkerPort` arguments; all requests stay on `127.0.0.1`, without
proxy inheritance or redirects.

The check:

1. Requires both services to report `2.0.17`, and the actual running worker to
   report a frozen build stamped with commit
   `3d52cc97735b9572225cc5776d9ebc16656951b6` and published executable SHA-256
   `9a7cfbaa2e69565e30fab387076d1e099d9d65173218e0cf677ce84a7f1ddea6`.
2. Requires ASR, TTS and CUDA availability, and ASR configured for `cuda`.
3. Synthesizes a short Danish phrase through the current TTS configuration,
   retaining the actual selected provider in the report.
4. Sends that generated WAV through the actual ASR endpoint. A non-empty
   transcript and segments are required. There is no CPU fallback in the helper.
5. Rechecks the release identity and ASR configuration after inference.

First use can load or download the configured ASR model and use GPU memory. The
per-inference timeout is 300 seconds, adjustable with
`-InferenceTimeoutSeconds`. Elapsed times are diagnostic observations, not
baseline latency measurements. No exact transcript or voice-quality claim is
made from this synthetic roundtrip.

Each run creates a unique directory under `C:\Rig\ModelRig\diagnostics`, with
`installed-voice.json` and, after successful synthesis, `synthetic-da.wav`. The
console prints its location. Exit code 0 means this diagnostic passed; exit code
1 means it failed, with the failing stage and available worker error retained in
the JSON. A `503` CUDA/model error is distinct from missing ASR/TTS. Do not try to
repair a frozen executable by installing packages into an unrelated Python.

## Physical checks still needed

A diagnostic pass does **not** close V1. It does not exercise a microphone,
Android UI, the LLM/conversation pipeline, stop/barge-in, natural Danish quality
or the authoritative human-recording voice baseline. Its JSON explicitly marks
the audio as synthetic and V1 acceptance as false. It never writes into
`validation/` or changes any readiness or activation decision.

For the afternoon app test, use the existing conversation and check:

- A short spoken Danish message produces a transcript and an audible answer.
- A longer answer finishes and releases the recording/playback state so the next
  turn can start.
- The earlier same-thread secret, `blå elefant`, is available when asked for it.
- Markdown and punctuation sound natural in speech.
- Stop/barge-in stops the answer and permits a new turn.

These are practical observations to retain, not a replacement for the physical
acceptance gates. [VOICE_BASELINE.md](../VOICE_BASELINE.md) remains the authority
for the fixed human recordings, cold/warm measurements and manual Pixel trials;
[PHYSICAL_VALIDATION_CAMPAIGN.md](../PHYSICAL_VALIDATION_CAMPAIGN.md) defines the
remaining physical proofs and final disposition.

The helper's automated tests use mocked loopback APIs and a synthetic fixture
WAV on both Windows PowerShell 5.1 and PowerShell 7. They test identity checks,
failure handling and reporting; they do not prove GPU inference on the rig.
