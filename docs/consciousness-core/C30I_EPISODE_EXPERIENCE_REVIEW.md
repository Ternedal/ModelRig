# C30-I — Trusted episode experience review

Status: draft, stacked on C30-H, `production_activation=false`.

C30-I creates the explicit semantic review boundary between bounded C30-H
episode-closure evidence and the existing C7 `ExperienceCandidate` / Memory 4
handoff policy.

It deliberately does **not** manufacture an `ExperienceCandidate` from an
episode by itself.

## Why no synthetic candidate factory

A C30 experiential episode may span several cognitive cycles, while the current
C7 `ExperienceCandidate` contract requires one exact `cycle_id`.

C30-I therefore refuses to invent a synthetic cycle merely to make the schemas
fit. A caller may present a real C7 candidate with real cycle provenance, and
the review boundary verifies that candidate against the exact episode-closure
evidence.

## Review plan

`plan_episode_experience_review` returns:

- `NO_REVIEW` for an empty closed episode;
- `TRUSTED_REVIEW_REQUIRED` for a non-empty episode.

The plan explicitly says that raw text and chain-of-thought are unavailable,
completed-turn authority is unavailable, synthetic cycles are forbidden, no
candidate has been created, and Memory 4 has not been called.

## Trusted review

A `TrustedEpisodeExperienceReview` binds an external trusted reviewer to:

- the canonical C30-H closure-evidence ref;
- an explicit APPROVE/REJECT decision;
- one exact C7 candidate ref when approved;
- an operator or trusted semantic-review source ref.

C30-I does not infer that trust from an LLM response.

## Candidate admission

An approved candidate must:

- bind the same Self and Person Revision;
- use the exact closed episode ref as `event_ref`;
- include the canonical closure-evidence ref in `source_refs`;
- not introduce participants or active goals absent from the closure evidence;
- not claim `USER_STATED_FACT`;
- not carry `completed_turn_source_ref`;
- use only `inferred` or `shared_event` provenance.

These rules prevent bounded structural episode evidence from being laundered
back into the privileged C7 completed-turn path.

## C7 remains authoritative

After admission, C30-I calls only the pure existing
`plan_memory_handoff(candidate)` policy.

For every episode-derived candidate, the result must remain
`trusted_review_required`. Any unexpected automatic write authority fails
closed.

C30-I does not call a Memory 4 service and does not persist either the candidate
or the episode.

## Authority boundary

C30-I adds no:

- durable-memory write;
- Memory 4 service call;
- synthetic cognitive cycle;
- model call;
- SelfState write;
- scheduler or timer;
- tool/Agent 3 execution;
- identity/personality mutation;
- production activation.

## Qualification

Focused tests prove empty/non-empty review planning, rejection semantics,
identity and exact episode binding, provenance binding, participant/goal
anti-invention, no reconstructed USER_STATED_FACT, no completed-turn authority,
and a successful reviewed candidate reaching C7 only as
`trusted_review_required`.

## Next slice

C30-J may define a bounded process-local review mailbox/receipt lifecycle so a
review request can be surfaced and consumed exactly once without becoming a
parallel durable memory queue.
