# Kaliv ecosystem integration — 2026-10-23

This document describes integration boundaries, not a claim of production readiness. Consult this repository's README and implementation-specific documentation for supported commands and exact release gates.

## Repository role

**ModelRig** is part of the Kaliv ecosystem. Kaliv is the user-facing experience; ModelRig coordinates backend cognition, authenticated APIs and orchestration. Components retain independent ownership and release gates.

## Related repositories

- [ModelRig](https://github.com/Ternedal/ModelRig) — backend, memory, orchestration, tools and release coordination.
- [BodyRig](https://github.com/Ternedal/BodyRig) — body identity and motor state.
- [VoiceRig](https://github.com/Ternedal/VoiceRig) — voice profiles and synthesis runtime.
- [VisionRig](https://github.com/Ternedal/VisionRig) — structured visual perception.
- [LanguageRig](https://github.com/Ternedal/LanguageRig) — Danish language-model training and evaluation.
- [Kaliv](https://github.com/Ternedal/Kaliv) — public website and product presentation.
- [KalivHub](https://github.com/Ternedal/KalivHub) and [KalivHub-Receiver](https://github.com/Ternedal/KalivHub-Receiver) — Home Assistant/Cast dashboard sender and display-only receiver.
- [SkyPlayer-Engine](https://github.com/Ternedal/SkyPlayer-Engine) — shared XR/media playback primitives.

## Integration rules

1. Keep private credentials, user media and training sources out of Git and diagnostic bundles.
2. Authenticate cross-device ingress; use least privilege and explicit consent for tool execution.
3. Preserve subsystem ownership: VisionRig observations do not themselves authorize memory writes or actions; BodyRig owns body identity; VoiceRig owns voice packages.
4. A passing unit test or successful local prototype is not evidence of end-to-end physical acceptance. Record exact commit SHAs, hardware, test procedure, results and any outstanding gates.
5. Keep generated image/video media on a configured external storage volume when deploying ModelRig media workflows; clients must retrieve media via authenticated APIs rather than local filesystem assumptions.
6. Changes that affect runtime contracts require coordinated compatibility testing and an explicit release decision. Documentation-only changes should not silently change release status.

## Documentation checklist

- [ ] Confirm implementation against the current default branch and update feature status.
- [ ] Verify installation, environment variables, ports and upgrade/rollback commands on target hardware.
- [ ] Document API contracts, authentication, error handling and integration examples.
- [ ] Record reproducible tests and separate software checks from physical acceptance.
- [ ] Link to the exact released version and migration notes when applicable.

> This cross-repository guide is a documentation alignment starting point. Unchecked items are not verified or complete.
