# C22-B — Strict production CognitiveProfile configuration

Status: draft, resolver-only, no route and no model invocation.

C22-B solves a data-honesty problem before turn-coupled cognition is allowed to
become production-reachable.

The existing CognitiveProfile contract requires normalized values such as
reasoning depth and planning capacity. ModelRig has no benchmark authority that
can truthfully produce those numbers for an arbitrary installed model.

> **Unknown model capability is not permission to invent a score.**

## Configuration path

The resolver reads:

```text
KALIV_CONSCIOUSNESS_PROFILE_PATH
```

Default:

```text
./consciousness-profile.json
```

This is a setting, not an activation switch.

If the file does not exist, resolution returns unavailable.

No fallback profile is constructed.

## Strict config shape

Example:

```json
{
  "schema": "kaliv-consciousness-core/production-cognitive-profile-config/v1",
  "provider": "ollama",
  "model": "qwen2.5-coder:7b",
  "reasoning_depth": 0.55,
  "planning_capacity": 0.45,
  "context_capacity_tokens": 8192,
  "multimodal_capacity": 0.0,
  "tool_reasoning": 0.0,
  "uncertainty_calibration": 0.5,
  "source_ref": "operator-profile:local-cognition-v1",
  "capacity_basis": "operator_declared",
  "production_activation": false
}
```

The normalized values are explicit operator declarations.

They are **not** reported as benchmark measurements.

## Parsing boundary

The config file is bounded to 16 KiB.

Resolution rejects:

- empty files;
- invalid UTF-8;
- invalid JSON;
- duplicate JSON keys;
- non-object roots;
- unknown/extra fields;
- missing fields;
- non-finite values;
- booleans used as numeric capacities;
- normalized values outside 0..1;
- invalid context capacity;
- any `capacity_basis` other than `operator_declared`;
- `production_activation=true`.

The resolver does not import the Ollama provider to parse the file.

## Deterministic projection

A valid config produces one existing
`kaliv-consciousness-core/cognitive-profile/v1` value.

C22-B derives:

```text
config_ref
    = sha256(canonical strict config)

profile_id
    = hash(config_ref + projection version)

engine_instance_id
    = hash(provider + model + source_ref)
```

The actual declared capacity fields are copied exactly.

The projected CognitiveProfile always has:

```text
ephemeral=true
identity_authority=false
persistent_state_authority=false
action_authority=false
production_activation=false
```

Changing the config changes the canonical profile identity.

Changing the model therefore changes the transient cognitive profile, not the
durable self/person identity.

## Resolution receipt

The resolver returns an immutable receipt containing:

- canonical config ref;
- canonical CognitiveProfile ref;
- operator source ref;
- provider/model;
- `capacity_basis=operator_declared`;
- `measured_capability_claim=false`;
- `profile_ephemeral=true`;
- all identity/state/action authority false;
- `model_calls=0`;
- `production_activation=false`.

The distinction between *declared* and *measured* is explicit in the receipt.

## Missing config semantics

Missing file:

```text
resolve_production_cognitive_profile(...) -> None
```

This is not an error and it is not replaced by defaults.

A future production cognition route can therefore return “profile unavailable”
rather than silently assigning invented scores.

Malformed or contradictory files are different: they fail closed with
`ProductionCognitiveProfileError`.

## Authority boundary

C22-B adds no:

```text
route
activation switch
model call
Ollama import/call
automatic cognition
scheduler
thread
timer
SelfState write
Memory 4 write
action/tool authority
identity/personality mutation
```

It only resolves explicit local capability metadata into an ephemeral profile.

## What this unlocks

C22-A can already bind one cognitive step to a required event.

C22-B now supplies an honest path to the profile that such a production step
needs:

```text
operator-declared profile config
        |
        v
strict C22-B resolver
        |
        v
ephemeral CognitiveProfile
        |
        v
C22-A required-event one-shot step
```

A later slice can mount this as a separately gated private one-shot cognition
surface without inventing model capability metadata.
