# Consciousness Core — roadmap

Status: active side-track implementation. No production activation. Runtime and operator surfaces remain explicitly gated and default-off.

## Current stacked focus — C30 experiential episode and review

C30-A through C30-G establish bounded experiential episodes, live episode
admission/context, trusted boundary policy and non-destructive boundary
application.

C30-H through C30-T add the optional review path for closed episodes:

- C30-H: bounded reference-only closure evidence;
- C30-I: trusted semantic review boundary into existing C7 evaluation;
- C30-J: bounded process-local review mailbox;
- C30-K: non-blocking publication from C19 boundary application;
- C30-L: trusted bounded list/consume adapter;
- C30-M: exact APPROVE/REJECT decision application;
- C30-N: claim/abandon/commit lifecycle with semantic preflight before consume;
- C30-O: independently default-off loopback-only review transport;
- C30-P: independently default-off process-local review runtime lifecycle;
- C30-Q: privacy-safe runtime status;
- C30-R: aggregate process-local observability without per-request audit data;
- C30-S: read-only operator-attention evaluation with no notifications/actions;
- C30-T: compact privacy-safe operator summary.

C30-U provides the static capability manifest and consolidated qualification
contract for the complete C30-H through C30-T review capability.

The review path remains subordinate to existing authorities: Memory 4 owns
durable autobiographical memory; C7 handoff policy remains authoritative;
Agent 3 owns execution; Person/Profile owns identity/person revision; the review
control plane performs no model call and production_activation remains false.

## Foundation slices: C0–C3

### C0 — architecture authority

Deliver:
- authority map;
- non-goals and isolation boundary;
- explicit model-external invariant;
- personality multi-source boundary;
- BodyRig/VoiceRig/Memory 4/Agent 3 ownership boundaries.

Acceptance:
- no runtime import or route;
- no new action, durable-memory, or activation authority;
- exact phrase used consistently: **Consciousness Core**.

### C1 — SelfState + WorldState contracts

Deliver:
- versioned `SelfState` schema;
- versioned `WorldState` schema;
- deterministic valid fixtures;
- invariants proving SelfState contains no model/provider identity.

Acceptance:
- state can conceptually survive process restart and ThoughtEngine replacement;
- every world proposition carries provenance and confidence;
- production activation remains false.

### C2 — Cognitive Workspace contract

Deliver:
- bounded candidate set;
- bounded selected attention set;
- explicit candidate kinds;
- deterministic contract checks.

Acceptance:
- workspace carries information only;
- no tool/action/scheduler authority;
- selected attention remains bounded even when candidate input is larger.

### C3 — external ThoughtEngine contract

Deliver:
- transient `CognitiveProfile`;
- `ThoughtRequest`;
- `ThoughtProposal`;
- deterministic contract checks proving proposals have no persistent-state,
  memory-write, action, or identity authority.

Acceptance:
- swapping CognitiveProfile/engine leaves SelfState identity fields untouched;
- proposal schema has empty action/state-mutation surfaces;
- engine authority flags are all false;\n- weak/strong mock engine profiles may change cognitive output/uncertainty while\n  SelfState remains byte-for-byte unchanged.

## Original staged roadmap

### C4 — first runtime ThoughtEngine adapter
Default-off adapter integration. Mock engine remains the reference deterministic
test implementation; real model adapters are replaceable.

### C5 — prediction + metacognition
Predicted outcomes, observed outcomes, prediction error, confidence calibration,
known limitation/capability state.

### C6 — Personality Resolver
Compose stable Person/Profile personality with BodyRig, VoiceRig, memory and
behavioural evidence. BodyRig is one evidence source, not the sole personality
authority.

### C7 — experience / Memory 4 loop
Bounded ExperienceCandidate generation and existing Memory 4 authority for any
durable persistence.

### C8 — embodiment loop
Mock EmbodimentState first, then real BodyRig/Kaliv-VR observations. Preserve the
distinction between renderer state, observed state and inferred state.

### C9 — persistent goals
Long-lived goal state and intention formation. Agent 3 remains execution authority;
Core cannot bypass confirmations, tool gates, or existing safety boundaries.

### C10 — consolidation
Evidence-based self/world/personality consolidation with provenance, anti-drift
rules, model-swap regression tests, and explicit human/revision boundaries where
identity-bearing state changes.

## First product-independent milestone

Prove:

> Kaliv can replace ThoughtEngine A with ThoughtEngine B while preserving the same
> Person binding, SelfState identity, personality references, history, goals and
> durable memories.

Capability may improve or degrade. Identity may not be replaced.
