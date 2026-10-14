# Kaliv / ModelRig V1.0.0 — release candidate (known issues)

Date: 2026-10-15

Release policy: ship V1 with documented noncritical defects. This branch snapshots the current protected production main and does not include unvalidated experimental streaming fixes.

## Known issues
- Voice streaming may fail while opening temporary input.wav or creating a synthesized chunk.
- End-to-end ASR → LLM → TTS streaming has not passed physical acceptance on the Windows test worker.
- Streaming fixes are isolated in draft PR #2193; they are not part of this release candidate.

## Release scope and safeguards
- Do not claim voice streaming is reliable.
- Keep protected main and production workers (8080/8099) unchanged.
- Treat voice streaming as experimental until a physical test passes.
- No additional features are required to mark this candidate ready for packaging.

## Publication status
This is a **release candidate branch**, not a published GitHub Release, deployed service, or installer. Actual publication must be performed by a release-capable workflow or operator.
