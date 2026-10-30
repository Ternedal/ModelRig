# Documentation status and verification plan

Updated: 2026-10-23. This page separates verified repository facts from pending integration acceptance. It does not declare a new release.

## Known documentation anchors

- [README](../README.md): product definition, current architecture and V1 convergence gates.
- [Kaliv ecosystem map](KALIV_ECOSYSTEM.md): subsystem ownership and proposed KalivNexus boundaries.
- [KalivNexus](https://github.com/Ternedal/KalivNexus): currently documented as an API/capability-broker **proposal**, not a verified ModelRig runtime dependency.
- [BodyRig](https://github.com/Ternedal/BodyRig), [VoiceRig](https://github.com/Ternedal/VoiceRig), [VisionRig](https://github.com/Ternedal/VisionRig): independent authorities and evidence gates.
- [LanguageRig](https://github.com/Ternedal/LanguageRig): separate training pipeline, not a substitute for ModelRig inference.
- [KalivHub](https://github.com/Ternedal/KalivHub): Home Assistant/Cast dashboard; the receiver must remain display-only.
- [SkyPlayer-Engine](https://github.com/Ternedal/SkyPlayer-Engine): reusable VR/media primitives.

## Operator verification matrix

| Area | Documentation expectation | Acceptance evidence required |
| --- | --- | --- |
| Chat and memory | State exact backend/client versions and persistent-memory behavior | Cold-start and multi-turn recall on target rig |
| Voice | Separate ASR, streaming TTS and fallback paths | Short/long utterances, audio playback and latency |
| Image/video | Record backend, job lifecycle and client gallery API | End-to-end generation, external-drive storage and Android/VR retrieval |
| Body and perception | Preserve BodyRig/VisionRig authority | Exact-SHA software tests plus real-device tests |
| Nexus tools | Describe provider trust, consent and quotas | Versioned contract tests and side-effect authorization |
| Release | Keep production activation independent of documentation | Required CI, hardware gates, manifest and rollback evidence |

## Update discipline

1. Review implementation and existing docs on the same exact revision.
2. Mark each capability as proposed, implemented, automated-test verified, physically tested or released.
3. Never infer release readiness from a successful PR or from an isolated smoke test.
4. Keep secrets, training sources and user media out of documentation and CI artifacts.
5. Record commands only after verifying them against the current repository.

This checklist intentionally leaves unverified implementation details unresolved.
