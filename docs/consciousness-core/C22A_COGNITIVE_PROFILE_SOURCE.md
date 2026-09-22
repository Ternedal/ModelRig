# C22-A — Operator-calibrated CognitiveProfile source

Status: draft, configuration-only, `production_activation=false`.

C22-A gives production Consciousness Core one strict source of transient
`CognitiveProfile` values.

It does not run cognition.

> **The model can be replaced. The Core does not guess what that model is good
> at.**

## Why this exists

C19-B deliberately requires the caller to provide a transient
`CognitiveProfile` for each explicit step.

That preserved the key architecture rule:

- Self/Person identity belongs to Core;
- the external model supplies cognitive capacity;
- replacing the model must not replace the person.

But production still had no authoritative source for that transient profile.
A caller would otherwise have to invent fields such as:

- reasoning depth;
- planning capacity;
- context capacity;
- uncertainty calibration.

C22-A removes that caller-owned guess.

## Configuration file

Default location:

```text
<KALIV_DATA_DIR>/kaliv-consciousness-profile.json
```

Optional path override:

```text
KALIV_CONSCIOUSNESS_PROFILE_FILE
```

This environment value is a **setting**, not an activation switch.

The default path is resolved without creating the data root.

A missing file means:

```text
no production CognitiveProfile is currently available
```

It does not fabricate a default profile.

## Config schema

Example:

```json
{
  "schema": "kaliv-consciousness-core/cognitive-profile-config/v1",
  "provider": "ollama",
  "model": "qwen3:14b",
  "reasoning_depth": 0.7,
  "planning_capacity": 0.65,
  "context_capacity_tokens": 32768,
  "multimodal_capacity": 0.0,
  "tool_reasoning": 0.5,
  "uncertainty_calibration": 0.8,
  "calibration_refs": [
    "benchmark:consciousness:local-v1",
    "operator:profile-review"
  ]
}
```

The profile must include at least one calibration/source ref.

The config cannot contain:

- identity authority;
- persistent-state authority;
- action authority;
- production activation;
- profile id;
- engine-instance id.

Unknown fields fail strict validation.

## Canonical identity

Core creates:

```text
profile_id =
    cog-<sha256(
        canonical validated config
        + fixed ThoughtEngine instance identity
    )[0:32]>
```

Therefore:

- JSON whitespace does not change profile identity;
- JSON key order does not change profile identity;
- changing the model does;
- changing a calibrated capability does;
- changing the ThoughtEngine instance identity does.

The resulting full `CognitiveProfile` also has its existing canonical
`cognitive_profile_ref`.

## Authority

Every produced profile fixes:

```text
ephemeral=true
identity_authority=false
persistent_state_authority=false
action_authority=false
production_activation=false
```

Those values do not come from the operator file.

They are constructed by Core.

A profile can describe that a model is good at tool reasoning without granting
the model a tool.

## Hot reload

The profile file is read fresh on every explicit load.

This means an operator can replace:

```text
model A + calibration A
        ↓
model B + calibration B
```

and the next explicit cognitive step can receive the new profile without:

- changing self_id;
- changing person_id;
- changing Person Revision;
- changing Personality;
- restarting the cognitive session.

That is the intended "cognitive upgrade/downgrade" seam.

## Strict file boundary

The file is bounded to 32 KiB.

C22-A rejects:

- invalid UTF-8;
- empty files;
- oversized files;
- non-object JSON;
- duplicate JSON keys;
- NaN/Infinity;
- unknown fields;
- duplicate calibration refs;
- out-of-range capability values;
- invalid engine-instance identity.

The loader does not return raw validation input through an HTTP surface because
C22-A has no HTTP surface.

## Receipt

A successful load returns a receipt containing:

- canonical config SHA-256;
- canonical profile ref;
- generated profile id;
- engine-instance id;
- calibration refs;
- original file byte count.

The receipt fixes:

```text
model_calls=0
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

## What C22-A does not do

It adds no:

- route;
- model call;
- cognitive cycle;
- event admission;
- scheduler;
- timer;
- thread;
- background reload watcher;
- SelfState write;
- Memory 4 write;
- tool execution;
- Agent 3 execution;
- BodyRig/VoiceRig actuation.

## Next slice

C22-B can now create one explicit private cognitive-step boundary:

```text
live C19-B session
+ current C22-A profile
+ pending supervisor events
-> exactly one session.step(...)
```

That boundary can remain separately gated and loopback-only.

It still does not require a continuous background cognition loop.
