# V1 release disposition — 2026-10-16

## Decision scope

Kaliv v2.0.15 is already published as a non-prerelease GitHub release: https://github.com/Ternedal/ModelRig/releases/tag/v2.0.15 . This record distinguishes **publication**, **personal-use acceptance**, and **broader public security approval**. It does not retroactively certify unobserved physical tests.

## Confirmed

- GitHub v2.0.15 release is published with an Android APK asset.
- Operator previously confirmed an installed 2.0.15 update and audible voice response on the physical rig.
- Operator reported short spoken turns working; longer turns sometimes remained in listening state.
- Existing operator testing included a two-turn memory probe, but persistence and final end-to-end history acceptance remain unverified.
- PR #2209 documentation/CI/exact-head qualification passed at 065044e47daf098effc0269ef845aeb7f1da3ec9.
- PR #2208 signing inventory/CI passed ordinary checks at b3e8baa5f054a60682815f4d2a33834be4d82a80; exact-head still pending when recorded.

## Disposition

**Already published:** Kaliv 2.0.15.

**Personal-use V1:** eligible for operator acceptance with known limitations; not represented as independently certified or free of voice defects.

**Public distribution security:** hold on broader promotion until tracked Android signing credentials exposure has an owner-approved migration/rotation and upgrade compatibility decision. Do not disclose or regenerate signing secrets in this documentation PR.

**Freeze:** protect the deployed runtime candidate. Documentation-only changes can be separately reviewed and merged by explicit policy; runtime changes must remain in isolated branches until a new version is approved. No automatic merges.

## Focused residual checks (do not redo proven work)

1. Record exact deployed app/worker/backend SHA and signing fingerprint against the release artifact.
2. Retest long Danish utterances, spoken punctuation handling, and cross-turn memory on the installed 2.0.15 build. Record PASS/FAIL and logs; don't infer pass from a short utterance.
3. Verify interruption/cancellation and reconnect/upgrade data retention if those paths are release requirements.
4. Obtain owner decision on signing-key exposure and public distribution risk.

## Next development phase

Once the operator accepts the personal-use build, start V1.1 stabilization in feature branches; keep V1 artifact reproducible and main protected. Avoid conflating release publication with all acceptance gates passing.
