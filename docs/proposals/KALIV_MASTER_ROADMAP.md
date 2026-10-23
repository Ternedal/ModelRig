# Kaliv Master Roadmap — continuous delivery control (v1)

**Status:** proposed operating contract; not a claim that all repositories are integrated or production-ready.
**Source of truth:** GitHub issues/PRs, required CI checks, release tags and explicit physical-test evidence.
**Scope:** ModelRig, Kaliv, KalivNexus, VoiceRig, VisionRig, BodyRig, LanguageRig, KalivHub, KalivHub-Receiver and SkyPlayer-Engine.
**Protection:** no automatic merges, production deployments or changes to protected main branches.

## North-star outcome

A usable Kaliv improves continuously. Deliver vertical user journeys, not disconnected components. Every increment must identify a user-visible behavior and its evidence. An isolated prototype is never labelled integrated.

## Delivery cadence (targets, not promises)

- Each development session: select one highest-priority unblocked vertical slice, implement, test and link evidence in a PR.
- Daily when work is active: review CI failures, blocked work and PR aging; fix regressions before expanding scope.
- Every 2–3 days: target a demonstrable end-to-end improvement, with a fixture/demo if physical hardware is unavailable.
- Weekly: produce a release candidate only when all applicable gates pass; otherwise publish blockers and next actions.
- Every two weeks: inspect actual user journeys and re-rank priorities based on measured reliability and value.

## Definition of done

1. Scope and user journey documented, with owner repository and acceptance criteria.
2. Changes in a reviewable PR; branch protection and required checks honored.
3. Unit, contract, security and integration tests pass for affected boundaries.
4. Measured behavior is evidenced (test run, artifact, logs with secrets redacted).
5. Physical acceptance is recorded when required; never infer it from CI.
6. Rollback and migration implications are recorded; release version and compatibility reviewed.
7. Status is one of: planned, in_progress, blocked, code_complete, ci_verified, integrated, physical_verified, released. Do not skip evidence gates.

## Priority queue and dependencies

| Order | Vertical slice | Owner(s) | Exit gate |
| --- | --- | --- | --- |
| P0 | Trusted identity and scoped approval authority | ModelRig | Revocation, authorization, replay and audit tests; no real execution until reviewed |
| P0 | Read-only NAS/Home Assistant task | ModelRig + KalivNexus | End-to-end fixture + live read-only consented test; zero write capabilities |
| P0 | Task continuity Android ↔ Windows | Kaliv + ModelRig | Same task and revision after disconnect/restart |
| P1 | Bounded Swarm executor | ModelRig + KalivNexus | Sandboxed execution, budgets, verifier, idempotent receipts |
| P1 | Voice conversation quality | VoiceRig + ModelRig + Kaliv | Long utterances, streaming latency, no symbol readout, memory regression |
| P1 | Media generation → external storage → gallery | ModelRig + Kaliv | Quota, safe paths, video/image playback in clients |
| P2 | Hub status and home integrations | KalivHub + KalivHub-Receiver | Read-only by default, explicit device/room mapping |
| P2 | VR avatar and scene evidence | BodyRig + VisionRig + SkyPlayer-Engine | Physical XR test, provenance, real/simulated separation |
| P2 | Danish language quality | LanguageRig + ModelRig | Versioned evaluation set and regression threshold |

Dependencies: identity/policy before real side effects; Nexus adapter contracts before live tools; task identity before cross-device handoff; external media root before generation enabled; physical XR gates before release.

## Mandatory issue template fields

- **Journey / user-visible result**
- **Repository and owner**
- **Priority and dependencies**
- **Acceptance tests**
- **Security / privacy impact**
- **Evidence links** (CI run, test output, physical test)
- **Release/rollback notes**
- **Status and next action**, including a named blocker if blocked

## Scorecard (computed, never invented)

- Required CI pass rate, with numerator/denominator and checked time.
- Open PR age and time since last meaningful activity.
- Critical end-to-end journey pass rate; distinguish simulated from physical.
- Blocked issues with owner and next action.
- Changes released and rollbacks during reporting window.
- Median lead time from issue in_progress to verified delivery, where timestamps exist.

If source data is missing, show **unknown**; do not substitute 100%. CI success proves only the checks run, not production readiness.

## Drift response

- Critical regression: pause dependent merges, open blocking issue, attach failing evidence and fix or rollback.
- No demonstrated vertical slice in seven days: cut scope and select a smaller end-to-end deliverable.
- PR stalled over three days: identify blocker, split or close with rationale.
- Physical rig unavailable: continue mock/contract work but retain physical_verified=false.
- New feature idea: backlog it; do not silently displace the current P0 journey.

## Governance

The master roadmap is the coordination contract, not a replacement for repository-specific issues. PRs should reference their tracked issue and include test evidence. A weekly report must distinguish **verified now** from **planned**. Protected main and existing release freezes remain authoritative.

## Immediate implementation sequence

1. Establish master tracking issue and cross-repository links.
2. Add a read-only report collector that uses GitHub API with least-privilege token, timeouts, pagination and explicit missing-data states.
3. Add a CI workflow for report validation; schedule reporting only after token scopes and repository permissions are reviewed.
4. Connect the first NAS read-only vertical slice and measure it end to end.
