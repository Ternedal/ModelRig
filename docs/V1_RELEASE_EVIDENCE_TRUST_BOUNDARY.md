# V1 release evidence trust boundary (draft)

Baseline: ModelRig `0b2ff455116f4f28a1a41704d9cb81503f17d2df`. This document is an **operator safety addendum**, not release authorization. See issues #2025, #2109, #2111 and #2107.

## Current authority

- The system release manifest gate currently checks the **structure** of canonical evidence references. A structurally `QUALIFIED` manifest is **not** independent proof that the referenced physical tests occurred or passed.
- Synthetic 40/64-hex references in unit tests establish only format compatibility. Never copy them into real release evidence.
- Until each producer artifact is resolved, byte-hashed, revision-bound and independently reviewed, keep `release_ready=false`, `production_activation=false`, and all unverified physical/administrative gates `PENDING`.
- Do not create a release tag, sign/promote an artifact, or change frozen `main` based on a structural verdict.

## Frozen four-repository revision set

| Repository | Pinned SHA |
| --- | --- |
| ModelRig | `0b2ff455116f4f28a1a41704d9cb81503f17d2df` |
| BodyRig | `8a85597637d0b59947bd179366e27be1bb847c16` |
| VisionRig | `66ea9bfce1c4d219e4bac1d85324a0e6e3f042e5` |
| VoiceRig | `9f3e594996db7eb2c6e035247ecb168bf17c1dae` |

## Evidence acceptance checklist

For **each** mandatory gate, record the producer and exact artifact location; source repository and exact SHA; producing command and validator version/source SHA; measured artifact SHA-256 computed from retrieved bytes; run timestamp and environment; and operator approval identity/time when required. Independently replay the canonical producer qualifier. Missing, inaccessible, stale, inconsistent, untrusted or unreviewed evidence means **PENDING/FAIL**, never PASS.

Repository authority is not uniform at the frozen revisions: ModelRig and BodyRig support `./verify-repository-authority.ps1 -Json`; VisionRig and VoiceRig support `./verify-repository-authority.ps1` **without** `-Json` and only yield observational text. Independently verify exact checkout SHA, clean worktree and authenticated GitHub branch protection with sufficient permissions before making any authority claim. Do not translate legacy text output into a canonical PASS receipt.

## Required adversarial regression cases for a future verifier

1. Ten syntactically valid but invented digest references must **not** produce authoritative release approval.
2. A real artifact with altered bytes must fail its recorded SHA-256 comparison.
3. An artifact from another repository revision must fail exact-SHA binding.
4. Missing producer output, human sign-off or permissions must fail closed.
5. A structural-only verdict must never be interpreted as physical qualification.

## Change discipline

This document is isolated from the frozen V1 `main`. Implement artifact-resolving validation and tests in a separate reviewed change. Merging **any** change into the frozen baseline requires explicit re-freeze and complete exact-head requalification. The authoritative physical campaign remains #2025. Historical 2.0.11/2.0.13 updater commands in `PHYSICAL_VALIDATION_CAMPAIGN.md` are not instructions to release 2.0.14.
