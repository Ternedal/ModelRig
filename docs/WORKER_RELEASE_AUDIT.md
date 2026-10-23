# ModelRig worker and release configuration audit

Source inspection: 2026-10-23. Reviewed `VERSION`, `worker/requirements.txt`, `worker/requirements-release-voice.txt`, `.github/workflows/ci.yml` and `.github/workflows/build-and-release.yml` on main. This is static inspection; no CI run, build or release was triggered.

## Version and dependency sources

- `VERSION` contains **2.0.18** at inspection time. This does not independently prove the currently deployed version.
- Base worker dependencies are pinned with `==`, including FastAPI 0.143.0, Uvicorn 0.52.4, httpx 0.28.1, Pydantic 2.13.5, cryptography 50.0.1 and tzdata 2026.5.
- Release voice requirements pin faster-whisper 1.2.1, soundfile 0.13.1, Piper TTS 1.4.2, and Windows CUDA/cuDNN runtime wheels.
- The base requirements comment labels ASR/TTS optional for a lightweight worker; the Windows release workflow installs the separate release voice requirements explicitly.

## Workflow behavior verified from YAML

- `ci.yml` responds to main pushes, pull-request events and manual dispatch. Its reusable `_tests.yml` suite and Windows worker packaging job are distinct gates.
- The Windows packaging job checks out the expected exact SHA, installs Python 3.11 and Go 1.23, creates a PyInstaller worker and verifies the frozen voice payload.
- `build-and-release.yml` responds to `v*` tags and manual dispatch; version-check compares declared version sites and the release tag with `VERSION`.
- The release workflow comments describe direct release-asset upload rather than an intermediate GitHub artifact hop. The complete workflow should be reviewed before asserting final asset/signature guarantees.

## Verification required before operator use

- [ ] Verify the exact running server/worker/updater versions and build identity on the physical rig.
- [ ] Confirm the complete required-check list and successful CI for the PR head.
- [ ] Inspect release workflow's actual asset, signature, attestations and rollback steps.
- [ ] Test short/long ASR, streaming TTS, durable memory and authenticated media access.
- [ ] Confirm external-drive storage and client retrieval of generated images/videos.
- [ ] Do not equate a matching `VERSION` file or passing documentation PR with production activation.

See [documentation status](DOCUMENTATION_STATUS_2026-10-23.md) and [ecosystem integration](KALIV_ECOSYSTEM.md).
