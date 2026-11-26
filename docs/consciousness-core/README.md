# Consciousness Core — documentation index

Index of the documents in this directory, grouped by the C-phase each document
names itself with. Each line is the document's own title. For the current
implementation and activation state, see the generated
[`CURRENT_STATE.md`](../../CURRENT_STATE.md) and
[`ACTIVATION_READINESS.md`](../../ACTIVATION_READINESS.md) in the repository root.

## Architecture and roadmap

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — Consciousness Core — architecture authority
- [`ROADMAP.md`](ROADMAP.md) — Consciousness Core — roadmap

## C0–C3 — foundation contracts

C0–C3 have no separate slice documents; they are described in
[`ROADMAP.md`](ROADMAP.md#foundation-slices-c0c3) and [`ARCHITECTURE.md`](ARCHITECTURE.md).

## C4–C17

- [C4](C4_RUNTIME.md) — dormant runtime ThoughtEngine adapter
- [C5](C5_METACOGNITION.md) — prediction and metacognition
- [C6](C6_PERSONALITY_RESOLVER.md) — multi-source Personality Resolver
- [C7](C7_MEMORY4.md) — ExperienceCandidate and Memory 4 bridge
- [C8-A](C8_EMBODIMENT.md) — embodiment observation contracts and mock loop
- [C9-A](C9_GOALS.md) — persistent goals and intention lifecycle
- [C10](C10_CONSOLIDATION.md) — consolidation and anti-drift
- [C11](C11_TEMPORAL_SENSE.md) — Temporal Sense
- [C12](C12_SLEEP_DORMANCY.md) — Sleep / Dormancy
- [C13-A](C13_SLEEP_LIFECYCLE.md) — persisted sleep boundary
- [C13-B](C13B_WORKER_WIRING.md) — Authoritative worker sleep/wake wiring
- [C14](C14_SELF_STATE.md) — persistent runtime SelfState
- [C15](C15_COGNITIVE_CYCLE.md) — Authoritative cognitive cycle / inner-monologue boundary
- [C16](C16_POST_CYCLE_REDUCER.md) — Deterministic post-cycle reducer and next-state continuity
- [C17](C17_WAKE_FIRST_CYCLE.md) — Wake reorientation and first cognitive cycle

## C18

- [C18-A](C18A_SUPERVISOR_KERNEL.md) — Event-driven cognition supervisor kernel
- [C18-B](C18B_SUPERVISOR_LIFECYCLE.md) — Default-off production supervisor lifecycle seam

## C19

- [C19-A](C19A_RUNTIME_SESSION_BOOTSTRAP.md) — Authoritative runtime session bootstrap
- [C19-B](C19B_PRODUCTION_SESSION_OWNER.md) — Production in-memory cognitive session owner

## C20

- [C20-A](C20A_WORLD_STATE_REDUCER.md) — Provenance-bound epistemic WorldState reducer
- [C20-B](C20B_WORLD_SESSION_ADMISSION.md) — Atomic world-evidence admission into live session

## C21

- [C21-A](C21A_USER_TURN_ADMISSION.md) — Loopback reported user-turn admission
- [C21-B](C21B_NORMAL_CHAT_HOOK.md) — Normal /api/v1/chat user-turn hook

## C22

- [C22-A](C22A_COGNITIVE_PROFILE_SOURCE.md) — Operator-calibrated CognitiveProfile source
- [C22-B](C22B_PROFILE_BACKED_STEP.md) — Profile-backed private one-shot cognition step
- [C22-C](C22C_EXACT_EVENT_STEP.md) — Exact-event profile-backed one-shot cognition
- [C22-D](C22D_NORMAL_CHAT_COUPLING.md) — Opt-in normal-chat exact-event cognition coupling

## C23

- [C23-A](C23A_RESPONSE_GUIDANCE.md) — One-shot outward response-guidance mailbox
- [C23-B](C23B_RESPONSE_GUIDANCE_CONSUME.md) — Private one-shot response-guidance consume

## C24

- [C24-A](C24A_EXACT_SAME_TURN_GUIDED_CHAT.md) — Exact-turn guided normal chat orchestration

## C25

- [C25-A](C25A_AUTONOMOUS_TRIGGER_POLICY.md) — Bounded autonomous cognition trigger policy
- [C25-B](C25B_AUTONOMOUS_TICK.md) — Default-off one-tick autonomous cognition adapter
- [C25-C](C25C_SCHEDULER_CADENCE.md) — Scheduler-owned autonomous cognition cadence

## C26

- [C26-A](C26A_WAKE_FOLLOWUP.md) — Authoritative wake-followup event admission
- [C26-B](C26B_PREDICTION_ERROR.md) — Prediction-mismatch attention admission
- [C26-C](C26C_MEMORY_RECALL.md) — Privacy-safe Memory 4 recall attention
- [C26-D](C26D_EMBODIMENT_ATTENTION.md) — Semantic embodiment-change attention

## C27

- [C27-A](C27A_SELFSTATE_CHECKPOINT.md) — Atomic SelfState transition-chain checkpoint
- [C27-B](C27B_SELFSTATE_LEDGER.md) — Runtime SelfState transition ledger
- [C27-C](C27C_CHECKPOINT_COORDINATOR.md) — Explicit durable SelfState checkpoint coordinator
- [C27-D](C27D_SHUTDOWN_CHECKPOINT.md) — Default-off graceful-shutdown SelfState checkpoint
- [C27-E](C27E_CHECKPOINT_PRESSURE.md) — Deterministic SelfState checkpoint pressure policy
- [C27-F](C27F_POLICY_CHECKPOINT.md) — Explicit policy-driven SelfState checkpoint adapter
- [C27-G](C27G_POLICY_CHECKPOINT_SERVICE.md) — Default-off production policy-checkpoint service
- [C27-H](C27H_AUTONOMOUS_CHECKPOINT.md) — Default-off autonomous post-RUN SelfState checkpoint coupling
- [C27-I](C27I_EXACT_EVENT_CHECKPOINT.md) — Default-off exact-event SelfState checkpoint coupling
- [C27-J](C27J_TURN_CHECKPOINT.md) — Default-off user-turn/world SelfState checkpoint coupling

## C28

- [C28-A](C28A_SLEEP_SELFSTATE_BINDING.md) — Exact durable SelfState sleep/wake binding
- [C28-B](C28B_WAKE_ACK.md) — Single-use planned sleep wake acknowledgement
- [C28-C](C28C_UNPLANNED_DORMANCY.md) — Unplanned dormancy detection from wake acknowledgement marker

## C29

- [C29-A](C29A_LIVENESS_WITNESS.md) — Durable runtime liveness witness primitive
- [C29-B](C29B_CHECKPOINT_LIVENESS.md) — Committed-checkpoint liveness recorder
- [C29-C](C29C_POLICY_CHECKPOINT_LIVENESS.md) — Policy-checkpoint liveness coupling
- [C29-D](C29D_UNPLANNED_LIVENESS.md) — Liveness-bounded unplanned dormancy
- [C29-E](C29E_CONTINUITY_STATE.md) — Process-local post-wake continuity state
- [C29-F](C29F_CONTINUITY_CONTEXT.md) — Bounded continuity projection into C15 model context
- [C29-G](C29G_REORIENTATION_POLICY.md) — Continuity-driven reorientation policy
- [C29-H](C29H_WAKE_ATTENTION.md) — Continuity-aware wake attention wiring
- [C29-I](C29I_REORIENTATION_HORIZON.md) — One-successful-RUN post-wake reorientation horizon
- [C29-J](C29J_RECOVERY_COMPLETION.md) — Process-local recovery completion receipt
- [C29-K](C29K_ORIENTATION_PHASE.md) — Explicit recovery orientation phase
- [C29-L](C29L_STATUS_SNAPSHOT.md) — Read-only continuity status snapshot
- [C29-M](C29M_CONTEXT_RETIREMENT.md) — Post-recovery wake-context retirement

## C30

- [C30-A](C30A_EXPERIENTIAL_EPISODE.md) — Experiential episode primitive
- [C30-B](C30B_LIVE_EPISODE.md) — Live cognitive episode tracker
- [C30-C](C30C_EVENT_EPISODE_ADMISSION.md) — World and user-turn episode admission
- [C30-D](C30D_SEMANTIC_EPISODE_ADMISSION.md) — Semantic attention admission into experiential episodes
- [C30-E](C30E_EPISODE_CONTEXT.md) — Bounded current-episode model context
- [C30-F](C30F_EPISODE_BOUNDARY_POLICY.md) — Deterministic episode boundary policy
- [C30-G](C30G_BOUNDARY_APPLICATION.md) — Atomic episode boundary application
- [C30-H](C30H_EPISODE_CLOSURE_EVIDENCE.md) — Bounded episode-closure evidence
- [C30-I](C30I_EPISODE_EXPERIENCE_REVIEW.md) — Trusted episode experience review
- [C30-J](C30J_REVIEW_MAILBOX.md) — Bounded process-local review mailbox
- [C30-K](C30K_SESSION_REVIEW_PUBLICATION.md) — Non-blocking C19 review publication
- [C30-L](C30L_TRUSTED_REVIEW_ADAPTER.md) — Trusted in-process review adapter
- [C30-M](C30M_REVIEW_DECISION_APPLICATION.md) — Exact trusted review decision application
- [C30-N](C30N_REVIEW_CLAIM_SERVICE.md) — Trusted review claim service
- [C30-O](C30O_PRIVATE_REVIEW_API.md) — Private loopback-only episode review API
- [C30-P](C30P_REVIEW_RUNTIME_LIFECYCLE.md) — Episode review runtime lifecycle
- [C30-Q](C30Q_REVIEW_STATUS.md) — Privacy-safe episode review status
- [C30-R](C30R_REVIEW_OBSERVABILITY.md) — Privacy-safe aggregate review observability
- [C30-S](C30S_REVIEW_ATTENTION.md) — Read-only episode review attention policy
- [C30-T](C30T_REVIEW_OPERATOR_SUMMARY.md) — Compact operator review summary
- [C30-U](C30U_REVIEW_CAPABILITY_MANIFEST.md) — Episode review capability manifest and consolidated qualification

## C31

C31-A–C31-G are described in
[`ROADMAP.md`](ROADMAP.md#current-completed-stack--c31-lived-continuity-loop).

- [C31-H](C31H_LIVED_CONTINUITY_QUALIFICATION.md) — Privacy-safe operator status and consolidated qualification

## Live qualification and integration

- [`LIVE_CYCLE_QUALIFICATION.md`](LIVE_CYCLE_QUALIFICATION.md) — Live Consciousness cycle qualification
- [`LIVE_LIFECYCLE_QUALIFICATION.md`](LIVE_LIFECYCLE_QUALIFICATION.md) — Live Consciousness lifecycle qualification
- [`VISIONRIG_ADMISSION.md`](VISIONRIG_ADMISSION.md) — VisionRig -> Consciousness Core admission
