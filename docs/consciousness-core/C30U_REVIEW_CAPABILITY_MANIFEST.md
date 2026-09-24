# C30-U — Episode review capability manifest and consolidated qualification

Status: draft, stacked on C30-T. No production activation.

C30-U closes the current C30 review stack with a machine-readable contract for
the capability built across C30-H through C30-T.

The manifest describes static gates, routes, bounds and denied authorities only.
It contains no live review state.

## Capability chain

The qualified chain is:

closed experiential episode
  -> C30-H bounded closure evidence
  -> C30-I trusted semantic review boundary
  -> C30-J bounded process-local mailbox
  -> C30-K non-blocking C19 publication
  -> C30-L bounded trusted adapter
  -> C30-M exact APPROVE/REJECT application
  -> C30-N claim / abandon / semantic-preflight / commit
  -> C30-O private loopback transport
  -> C30-P independent review runtime lifecycle
  -> C30-Q privacy-safe status
  -> C30-R aggregate observability
  -> C30-S read-only attention evaluation
  -> C30-T compact operator summary

C30-U does not add another state machine to that chain. It describes and
qualifies the resulting capability.

## Independent gates

Runtime construction requires the exact opt-in:

KALIV_CONSCIOUSNESS_EPISODE_REVIEW_RUNTIME_ENABLED=1

Transport mounting requires the independent exact opt-in:

KALIV_CONSCIOUSNESS_EPISODE_REVIEW_ENABLED=1

Both default to off.

The manifest reports defaults, not current environment values.

## Operator read surfaces

All review transport routes are under:

/experimental/consciousness/episode-review

Read-only operator surfaces are:

- /manifest
- /status
- /attention
- /summary

Workflow surfaces are:

- /pending
- /claim
- /abandon
- /commit

The entire transport remains loopback-only.

## Bounds

The static manifest records:

- default mailbox capacity: 8;
- maximum mailbox capacity: 32;
- maximum pending list result: 32;
- maximum active claims: 32;
- aggregate observability maximum: signed 64-bit max.

These bounds are declarations backed by the underlying slice contracts; C30-U
does not introduce a second configurable source of truth.

## Core safety and authority contract

The manifest fixes the following facts:

- episode boundary application is not blocked by review publication;
- claim does not consume the request;
- semantic preflight occurs before consume;
- request/ref binding is exact;
- no synthetic cognitive cycle may be invented;
- closure evidence cannot be laundered into a synthetic USER_STATED_FACT;
- episode-derived review cannot gain completed-turn authority;
- no direct Memory 4 write authority exists;
- no durable review store or durable claim recovery exists;
- no automatic semantic reviewer exists;
- operator status carries no raw user text;
- no raw chain-of-thought is included;
- no automatic notifications exist;
- no timer, scheduler, background-worker or execution authority exists;
- the review control plane performs zero model calls;
- production_activation remains false.

## /manifest route

C30-O now exposes:

GET /experimental/consciousness/episode-review/manifest

The route is loopback-only and requires no live review runtime/service because
it describes a static contract.

It is still absent when the independent C30-O transport flag is off.

## Documentation alignment

C30-U updates ROADMAP.md and ARCHITECTURE.md because the old top-level wording
still described Consciousness Core as the C0–C3 contracts-only slice and stated
that it had no routes.

That historical invariant applied to the foundation slices. The current
architecture permits separately reviewed, explicitly gated, default-off runtime
and loopback operator surfaces while preserving the original identity, memory
and execution authority boundaries.

## Qualification

Focused tests prove:

- exact gate names/defaults;
- exact route inventory and bounds;
- authority-denial fields;
- static manifest behavior independent of current environment;
- absence of live ids/counts from the manifest;
- loopback-only service-free manifest access;
- no persistence/background runtime primitives in the manifest implementation.

## Landing rule

C30-U does not declare the stack qualified merely because this manifest exists.

The stacked PR chain remains subject to the repository's normal exact-head CI
and diagnostics. No slice should be represented as landed until its required
qualification has actually completed successfully.
