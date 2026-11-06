# Kaliv release acceptance matrix — operator baseline

> This document is a **planning and evidence-capture template**, not an assertion that tests passed. Never promote a release based on this file alone. Exact-head gates and independent physical qualification remain authoritative.
>
> **Historical baseline (16 October 2026):** The checklist below is an unfilled template, not the live status of installed v2.0.18. The temporary v2.0.18 merge freeze was lifted on 20 October 2026; merging documentation does not constitute release approval. Capture fresh evidence for the actual target SHA and published assets before any later promotion.

## Candidate identity

| Field | Required value |
| --- | --- |
| ModelRig commit SHA | NOT_RECORDED |
| BodyRig commit SHA | NOT_RECORDED |
| VoiceRig commit SHA | NOT_RECORDED |
| VisionRig commit SHA | NOT_RECORDED |
| GitHub release tag + release URL and publish timestamp | NOT_RECORDED |
| Immutable release asset inventory (asset filename, published URL, size and SHA-256 for every shipped artifact) | NOT_RECORDED |
| Signed/released distribution bundle or archive SHA-256 and attestation subject | NOT_RECORDED |
| Android application ID/version/signing fingerprint | NOT_RECORDED |
| Go backend + Python worker build IDs | NOT_RECORDED |
| Signed APK SHA-256 (versioned APK and kaliv-latest.apk) | NOT_RECORDED |
| Windows desktop JAR SHA-256 | NOT_RECORDED |
| Backend, worker, supervisor and updater EXE SHA-256 (each) | NOT_RECORDED |
| Release source ZIP and SHA256SUMS.txt SHA-256 | NOT_RECORDED |
| Signed checksums and build attestations (URLs, subjects and verification outcomes) | NOT_RECORDED |
| Operator/date/rig hardware | NOT_RECORDED |

## Evidence vocabulary

Use only `PASS`, `FAIL`, `BLOCKED`, or `NOT_RUN`. `PASS` requires dated, linked evidence for the **exact source and installed artifact bytes** (SHA-256, signature and provenance, not just a release name). A PR description or CI pass cannot substitute for a real device test. For **every physical observation**, record the source repository and exact commit, release tag, installed asset filenames, independently computed SHA-256 per installed APK/JAR/EXE/bundle, signing-certificate fingerprint where applicable, and verification of each attestation subject against those bytes; link the receipt to that immutable asset inventory. If any subject, hash, signature or installer identity is absent or mismatched, mark the affected gate `BLOCKED`, not `PASS`. Do not silently reuse a receipt from a rebuilt artifact with the same version.

## Mandatory acceptance

| Gate | Status | Required evidence |
| --- | --- | --- |
| All required exact-head CI and CodeQL | NOT_RUN | GitHub run URLs and candidate SHAs |
| Release asset completeness, hashes and provenance | NOT_RUN | Verify published asset names, SHA-256 hashes, signatures and attestation subjects against each installed APK/JAR/EXE/bundle/archive and checksum. Cross-check the release asset manifest and physical receipt hashes; missing identities or mismatches are BLOCKED |
| Cross-repo inventory/source authority | NOT_RUN | Bound manifests and reviewed transition receipts |
| Android mic permission and capture | NOT_RUN | Device log and operator result |
| Android → authenticated Go proxy → worker | NOT_RUN | Correlated request trace with credentials redacted |
| Danish ASR and local LLM answer | NOT_RUN | Controlled input, transcript and output |
| TTS audible first chunk and complete playback | NOT_RUN | Operator observation and timing |
| Stop during network stream cancels upstream work | NOT_RUN | Android, Go and worker cancellation evidence |
| Barge-in prevents stale audio and frees resources | NOT_RUN | Two-turn physical replay |
| Voice history recalls prior turn without system-role injection | NOT_RUN | Bounded two-turn replay and negative test; physical: `change-01` in `validation/voice-change-observations.json` (`START_STAGE_A_VOICE_TEST.cmd`) |
| Completed voice turns survive app restart; a finished turn returns to idle | NOT_RUN | `change-03` and `change-04` in `validation/voice-change-observations.json` (#2243, #2242) |
| Temporary WAV cleanup after interruption | NOT_RUN | Post-run filesystem inventory |
| Offline/reconnect and repeat turn | NOT_RUN | Device test and recovery trace |
| Cloud opt-in and privacy boundary | NOT_RUN | Local-only and explicitly cloud-enabled probes; only the current user message may reach the cloud (SECURITY.md D5): `change-02` in `validation/voice-change-observations.json` must show the cloud model did not know an earlier turn. `not_run` there keeps this row NOT_RUN |
| Installed-app upgrade retains app data | NOT_RUN | Version/signature/device-data evidence |
| Rollback/recovery | NOT_RUN | Approved operator runbook and recovery test |
| Existing signing-key risk decision still applies | NOT_RUN | Record evidence of whether the app remains solo, sideload-only, and on the user's own backend/Tailscale per `SECURITY.md` D1 (2026-07-13). If public distribution, additional users, or application-ID protection assumptions change, mark BLOCKED until explicit owner-approved risk reassessment and migration plan |

### Signing authority and accepted risk

`SECURITY.md` D1 (2026-07-13) explicitly **accepts** the existing public Android signing key for the stated solo / sideload-only deployment and directs that the key **not** be rotated or purged under those assumptions. Existing exposure is real; this matrix does not silently revoke that decision. The signing gate verifies that the acceptance assumptions remain true and records that decision with dated evidence. A trigger (public distribution, another user, or application-ID squatting protection) requires a new explicit owner decision; until then, mark the gate `BLOCKED`. No automatic key rotation or source-history rewrite is authorized.

## PR dependency review

- #2200: Android OkHttp cancellation (check actual current state).
- #2201: combined voice validation candidate.
- #2202: published v2.0.15 release branch (draft PR closed as superseded; verify tag and asset hashes).
- #2203: side-by-side device pilot.
- #2204: capabilities proxy; inventory-pinned source governance.
- #2205: original voice-history PR (superseded by #2211, stacked on #2210).
- #2206: opt-in Nest Hub mirroring; independently gated.
- #2207: audit and priorities (merged to main; verify latest SHA).
- #2208: read-only signing inventory (not a rotation control).
- #2210: published v2.0.15 source reconciliation to main (draft; physical gate).
- #2211: bounded voice-history port to released streaming runtime (stacked draft).

**Before each merge:** refresh current PR state and SHA; classify superseded work; verify the target branch and dependency graph; ensure no release freeze violation. No auto-merge based on this template.

## Performance measurements (baseline before tuning)

Record separately for cold/warm sessions: ASR latency, LLM prefill, tokens/sec, first TTS chunk, time to audible reply, total turn duration, peak/idle VRAM and RAM, CPU utilization, queue depth, cancellation time, and p50/p95 across at least 20 representative Danish prompts. Attach hardware, model quantization, context size and Ollama settings. Do not infer improvement without paired baseline.

## Exit criteria

All mandatory gates PASS with dated linked evidence, except any explicitly waived nonmandatory item with documented risk owner. Any FAIL/BLOCKED/NOT_RUN mandatory gate prevents production promotion. Approval must be explicit and independent of this document.
