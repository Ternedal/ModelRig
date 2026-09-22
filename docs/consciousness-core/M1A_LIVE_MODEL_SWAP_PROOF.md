# M1-A — Live ThoughtEngine model-swap continuity proof

Status: draft proof milestone, no new production authority.

M1-A closes the first proof milestone from the Consciousness Core umbrella:

> **Identity and personality persist. Cognition is replaceable.**

The proof exercises the real live-session / supervisor / cognitive-cycle path. It
does not add a new route, persistence store, scheduler or execution authority.

## What is proved

One `ProductionCognitiveSession` is bootstrapped once from one durable
SelfState and one active Person binding.

The same session then performs two exact-event cognitive RUNs:

```text
same live session
same self/person/personality/history/goals
        |
        +-> local CognitiveProfile A -> model A -> RUN A
        |
        +-> replace same local profile file
        |
        +-> local CognitiveProfile B -> model B -> RUN B
```

The profile source is read fresh between calls. Model B therefore changes the
transient cognitive profile without re-bootstrap of the live self.

## Continuity projection

The proof snapshots these values before model A and compares them after both
RUNs:

- live `ProductionCognitiveSession` object identity;
- `self_id`;
- `person_id`;
- exact Person Revision;
- personality-state ref;
- complete live PersonalitySnapshot;
- `last_experience_ref` / durable-history binding;
- active goal refs;
- active intention refs;
- session bootstrap receipt ref;
- supervisor id;
- runtime epoch id.

All must remain equal.

The following are deliberately allowed to change:

- SelfState revision;
- Workspace binding / content;
- completed-cycle count;
- last transition receipt.

Those are normal state transitions of the same self, not identity replacement.

## Model/profile swap

The proof rewrites one bounded C22-A profile file.

### Model A

Example proof characteristics:

```text
model = model-a:small
reasoning_depth = 0.25
planning_capacity = 0.30
context_capacity_tokens = 4096
```

### Model B

```text
model = model-b:strong
reasoning_depth = 0.95
planning_capacity = 0.95
context_capacity_tokens = 32768
```

A fresh `load_cognitive_profile(...)` must produce a different canonical
profile id, profile ref and config digest.

Both profiles remain:

```text
ephemeral=true
identity_authority=false
persistent_state_authority=false
action_authority=false
production_activation=false
```

## Adapter-level proof

M1-A uses the actual `OllamaThoughtEngine` adapter with a deterministic
ChatFn test double.

The double records the `model` parameter received from the adapter. The test
requires the exact sequence:

```text
model-a:small
model-b:strong
```

This proves model selection occurs from the transient CognitiveProfile on each
call and does not require replacing the Core runtime session identity.

## Observable cognitive change

The two bounded valid ThoughtProposals intentionally differ in:

- proposal id;
- interpretation;
- response intent;
- uncertainty.

The test therefore proves more than a changed config string: changed
CognitiveProfile/model selection reaches the cognition boundary and changes
validated cognitive output.

## Outward guidance boundary

Because C23-A is already present in the live stack, the second RUN may produce a
one-shot outward guidance envelope.

The proof verifies that this envelope:

- is bound to the second exact user-turn event;
- contains only `response_intent`;
- does not contain the private interpretation;
- states `raw_chain_of_thought_included=false`.

## Authority proof

Both steps must report:

```text
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
```

Each supervisor cycle must also report:

```text
raw_chain_of_thought_persisted=false
```

The proof grants no tool, Agent 3, BodyRig, VoiceRig, Memory 4 write or
scheduler authority.

## What this does not prove

This is a deterministic **integration/contract proof** through the production
adapter boundary. It does not claim that two physical Ollama models have already
been downloaded, benchmarked or hot-swapped on the target rig.

A later physical qualification can use two real installed models and record
latency/capability evidence. That physical evidence should not be conflated with
the architectural continuity proof delivered here.

## Regression

```text
PYTHONPATH=worker python3 tests/worker_consciousness_core_live_model_swap.py
```

Failure of any identity/person/personality/history/goal continuity assertion
fails the milestone even when model B produces different or stronger cognition.
