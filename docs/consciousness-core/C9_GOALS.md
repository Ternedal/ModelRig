# Consciousness Core C9-A — persistent goals and intention lifecycle

Status: first C9 slice. Serializable Core state only. No executor, scheduler or durable database.

Issue: #1619.

## Core rule

Consciousness Core may hold persistent goals and derive intentions.

Existing external authorities still decide whether and how an intention becomes an
action.

```text
GoalCandidate
  -> independent GoalAdmissionEvidence
  -> active GoalRecord
  -> deterministic arbitration
  -> selected IntentionRecord
  -> optional authority handoff
```

A ThoughtEngine suggestion is never itself goal activation authority.

## Goal admission

`GoalCandidate` has no active/status/execution fields.

Activation requires separate `GoalAdmissionEvidence` with one of the explicit
non-model authorities:

- user explicit;
- operator review;
- existing project commitment;
- maintenance policy.

The admitted priority comes from admission policy, not from the model's suggested
priority.

## Goal lifecycle

Goal state is serializable and model/provider independent.

Supported lifecycle:

```text
active -> paused | completed | abandoned | blocked
paused -> active | abandoned | blocked
blocked -> active | abandoned
```

Terminal completed/abandoned goals cannot reactivate through this contract.

Every transition requires provenance evidence and monotonically non-decreasing
sequence authority.

Completion additionally rejects model-only evidence such as
`thought-proposal:*`; declared success conditions plus non-model outcome evidence
are required.

## Arbitration

`select_next_goal()` is deterministic and receives no model/provider/CognitiveProfile.

It considers only active, non-expired goals and orders by:

1. admitted priority descending;
2. creation sequence ascending;
3. goal id for deterministic tie-break.

Goal existence is not permission to execute anything.

## Intentions

Only an active goal can create a selected `IntentionRecord`.

The intention records `required_authority`, for example:

- none;
- agent3;
- bodyrig;
- voicerig;
- memory4;
- human_review.

That field is routing metadata, not authority.

## Agent 3 handoff

C9-A can produce `Agent3IntentHandoff` only for an already-selected intention
whose required authority is exactly `agent3`.

The handoff explicitly contains:

```text
execution_started = false
```

It contains no tool plan, confirmation, run id or execution method.

Agent 3 / ToolGate remain the execution authority.

## Curiosity

A curiosity goal may exist under an admitted policy, but this does not grant
background execution, tools or scheduling.

C9-A creates no always-on autonomy.

## Persistence boundary

C9-A proves JSON serialization/reload of GoalRecord but does not introduce a new
database. Later composition may persist Core state through the approved
Consciousness Core state authority.

Memory 4 remains autobiographical memory authority; a memory record does not
activate a goal by itself.

## Non-goals

C9-A does not:

- create Agent3 runs;
- call tools;
- create confirmations;
- create schedules;
- mount routes;
- start background work;
- add a durable goal database;
- mutate Person/Profile;
- activate production.

`production_activation=false`.
