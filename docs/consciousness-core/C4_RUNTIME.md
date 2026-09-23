# Consciousness Core C4 — dormant runtime ThoughtEngine adapter

Status: stacked implementation over C0–C3. Default off. No route. No production activation.

Issue: #1614.

## Scope

C4 introduces one internal worker-side boundary:

```text
ThoughtRequest
  -> ConsciousnessCoreRuntime
  -> injected external ThoughtEngine
  -> strict ThoughtProposal validation
  -> caller receives proposal only
```

The runtime has no executor or persistent store.

## Activation

Only the exact value below composes the provider adapter:

```text
KALIV_CONSCIOUSNESS_CORE_ENABLED=1
```

Unset, `0`, `true`, `on`, and whitespace-padded values remain off.

The normal worker entrypoint does not import or mount Consciousness Core in this
slice. Therefore the flag alone creates no HTTP surface. A future route/mount
requires a separate reviewed change.

## Provider

The first concrete provider adapter reuses the existing asynchronous Ollama chat
client through dependency injection. The adapter is not identity authority:
provider/model live only in transient `CognitiveProfile`.

The provider receives no ToolGate, Agent 3 orchestrator, Memory 4 writer,
PersonRegistry, BodyRig session, VoiceRig mutation surface, scheduler, or durable
store.

## Fail-closed output

Model output must be one raw JSON object. Markdown fences, duplicate JSON keys,
unknown fields, invalid bounds, non-empty `actions`, non-empty
`state_mutations`, any authority bit set true, and request-id mismatch are
rejected.

A candidate intention may name `agent3`, `bodyrig`, `voicerig`, `memory4`
or `human_review` as required external authority. That is metadata on a proposal,
not a call to that authority.

## Non-goals

C4 does not implement:

- continuous cognition;
- SelfState persistence;
- Memory 4 read/write integration;
- Person/Profile mutation;
- Agent 3 execution;
- public/internal HTTP routes;
- background loops or scheduling;
- prediction/metacognition;
- personality resolution;
- embodiment feedback.

Those remain later Consciousness Core slices.

`production_activation=false`.
