# Consciousness Core — architecture authority

Status: architecture authority with reviewed default-off runtime slices, including the C30 experiential episode/review stack. Experimental and gated.
Authority basis: this document plus the existing Person/Profile, Memory 4, Agent 3, BodyRig and VoiceRig ownership boundaries.
Production activation: **false**.

## Purpose

Consciousness Core is the persistent cognitive coordination layer for Kaliv. It is
not a model, model host, agent executor, memory database, body runtime, voice
runtime, or claim of phenomenal consciousness.

The architectural invariant is:

> **Identity and personality persist. Cognition is replaceable.**

A model upgrade may improve reasoning, abstraction, planning, language, or
calibration. A downgrade may reduce those abilities. Neither is allowed to create
a new identity, rewrite durable personality, mutate autobiographical memory, or
gain action authority merely because the model changed.

Kaliv is not the model. Kaliv uses the model.

## Authority map

| Domain | Authority | Consciousness Core relationship |
| --- | --- | --- |
| Stable person identity / Person Revision | existing Person Profile authority | consumes exact active binding; cannot mint or activate a Person Revision |
| Durable personality identity | Person/Profile revision chain | consumes stable traits and revision refs |
| Personality evidence | Person Profile + BodyRig + VoiceRig + interaction/memory evidence | later Personality Resolver composes evidence; no single source is the whole personality |
| Durable autobiographical memory | Memory 4 authority | asks for bounded recall and may emit experience candidates; never writes durable memory directly |
| Body identity / movement realization | BodyRig | emits semantic body intent; later consumes observed EmbodimentState |
| Voice identity / speech realization | VoiceRig | emits semantic response/affect intent; voice authority remains VoiceRig-owned |
| External reasoning | ThoughtEngine adapter | calls a replaceable engine and receives proposals only |
| Tool/action execution | Agent 3 and existing tool/confirmation gates | emits intentions; cannot bypass execution authority |
| Self/world/workspace continuity | Consciousness Core | owns versioned state and bounded cognitive-cycle coordination |

## External ThoughtEngine

The model boundary is deliberately outside Consciousness Core.

```text
Consciousness Core
    |
    | ThoughtRequest
    v
ThoughtEngine adapter
    |
    | model/provider of the moment
    v
LLM / future cognitive engine
    |
    | ThoughtProposal
    v
Consciousness Core
```

The engine is stateless from the Core's authority perspective. An adapter may use
provider/session caches for performance, but those caches are never identity or
durable-state authority.

A ThoughtProposal can contain interpretations, hypotheses, candidate intentions,
predictions, questions, memory queries, attention suggestions, response intent,
body intent, and uncertainty. It contains **no direct state mutation or action
authority**.

The Core may reject, decompose, re-query, verify, or ignore any proposal.

## Persistent state

C1 defines two versioned state families:

- `SelfState`: identity binding, active goals/intentions, current affect,
  uncertainty, and references to current world/workspace/experience state.
- `WorldState`: bounded, provenance-bearing propositions about the currently
  relevant world.

SelfState intentionally carries no model, provider, or LLM identity. Cognitive
capacity is supplied transiently through a separate `CognitiveProfile` from the
ThoughtEngine adapter.

A stronger or weaker engine therefore changes capability without changing self.

## Cognitive Workspace

C2 defines a bounded workspace. Candidate events from perception, memory, goals,
body, voice, tool results, prediction errors, and prior thought results may compete
for attention. A bounded selected set becomes the active workspace for a cognitive
cycle.

The workspace is not an executor and cannot schedule work or call tools by itself.
It only selects information for cognition.

## Personality

Personality is explicitly multi-source. BodyRig is one source, not the whole
authority.

The later Personality Resolver will combine evidence from:

- stable Person/Profile personality revisions;
- BodyRig source-derived movement, posture, gaze, gesture, expressiveness, and
  other embodied traits;
- VoiceRig cadence, prosody, timing, and affective expression;
- durable interaction/memory evidence;
- stable behavioural evidence accumulated by Consciousness Core.

This is resolved into three distinct concepts:

1. **PersonalityIdentity** — slow-changing durable traits/values.
2. **PersonalityModel** — evidence-backed aggregate with provenance/confidence.
3. **PersonalityState** — current manifestation in the present situation.

Current affect is state, not identity. A surprising event must not rewrite a stable
personality revision.

## Body / embodiment boundary

Core emits semantics such as:

```text
affect: curious + mildly surprised
intent: attentive listening
```

It must not micromanage renderer values such as eyebrow percentages or exact head
angles. BodyRig remains responsible for source-derived realization through
BodyPrint, Movement Identity, Motor State, and later embodied-personality
projection.

A future C8 return path introduces `EmbodimentState` so the body becomes input as
well as output:

```text
intention -> BodyRig -> physical/renderer result -> observation
          -> EmbodimentState -> Consciousness Core -> next cognition
```

## Memory boundary

Memory 4 remains the durable-memory authority. Consciousness Core may request
relevant memories and may later emit bounded `ExperienceCandidate` records, but
the model never gets durable-write authority and the Core does not create a second
competing memory store.

## Core cognitive loop

The target loop is:

```text
observe
  -> update self/world state
  -> attention
  -> bounded workspace
  -> recall
  -> think through external ThoughtEngine
  -> verify / re-query if needed
  -> form intention
  -> existing execution / voice / body authority
  -> observe outcome
  -> compare prediction with outcome
  -> update experience/self/world
  -> next cycle
```

Multiple thought cycles may happen without an external action.

## Runtime isolation and activation invariant

C0–C3 began as contracts/docs/tests only. Later slices introduced reviewed
runtime integrations and private operator surfaces, but they do not weaken the
authority map above.

Current invariants are:

- production activation remains false in Consciousness Core contracts;
- runtime integrations require explicit default-off feature gates;
- private operator routes are independently gated and loopback-only where
  specified;
- mounting a transport route does not create the underlying runtime authority;
- the model never gains direct persistent-state, durable-memory, identity or
  execution authority;
- Memory 4 remains the only durable autobiographical-memory authority;
- Agent 3 and existing confirmation/tool gates remain execution authority;
- Person/Profile remains identity and Person Revision authority;
- optional review infrastructure is process-local unless a separately reviewed
  durable authority is introduced.

The C30 episode-review capability uses two independent exact opt-ins:

`KALIV_CONSCIOUSNESS_EPISODE_REVIEW_RUNTIME_ENABLED=1`

`KALIV_CONSCIOUSNESS_EPISODE_REVIEW_ENABLED=1`

The first constructs the bounded process-local review runtime. The second mounts
the loopback-only transport. Either may remain off independently. Neither grants
automatic Memory 4 persistence, model invocation, scheduling, notification,
tool execution or production activation.

## Scientific wording

Consciousness Core is an engineering name for a persistent cognitive architecture.
Passing its functional continuity tests is not by itself evidence that the system
has subjective experience. The implementation should measure concrete properties
such as continuity, self/world distinction, metacognitive calibration, prediction
error, model-swap continuity, and embodied feedback without introducing a
`conscious=true` product claim.
