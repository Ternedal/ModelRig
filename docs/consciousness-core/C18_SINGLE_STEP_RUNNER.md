# C18 — Exactly-one-cycle runtime runner

Status: draft, isolated, `production_activation=false`.

C18 is the first slice that composes the C15–C17 cognitive control chain into one
runtime step.

It deliberately does **not** create a cognitive loop.

```text
one C17 NEXT_CYCLE directive
        |
        v
explicit injected state commit
        |
        v
exactly one C15 cognitive cycle / ThoughtEngine call
        |
        v
exactly one C16 adjudication
        |
        v
exactly one C17 supervisor plan
        |
        v
return control to caller
```

## Transaction ordering

The C17 transition contains an in-memory next SelfState candidate and workspace.
Before any model call, C18 passes that exact transition to an injected
`StateTransitionCommitter`.

The committer must return a receipt proving:

- exact transition ID;
- exact source SelfState ref;
- exact committed next SelfState hash;
- exact next revision;
- a commit receipt reference;
- `persisted=true`.

Only after that receipt validates may the ThoughtEngine be invoked.

A rejected commit, exception, malformed receipt, wrong transition, wrong state
hash or wrong revision fails closed with **zero model calls**.

## Why persistence is injected

C14's current persistent SelfState store provides atomic file replacement and
strict revision checks, but it does not yet claim cross-process locking/CAS
authority for a production multi-writer runtime.

C18 therefore defines the transactional boundary without pretending the
concurrency problem is solved.

The runner imports no production SelfState persistence implementation. A later
slice can implement a narrow committer with explicit compare-and-swap/locking and
then inject it here.

## Exact one-step semantics

A successful C18 call performs exactly:

```text
state commits       = 1
model invocations   = 1
C16 adjudications   = 1
C17 supervisor plans= 1
recursive loop      = false
```

If the returned C16 decision is `ACCEPT_COGNITION`, the returned C17 directive
will normally be `COMPLETE`.

If it is `VERIFY`, `REQUERY` or `DECOMPOSE`, the returned C17 directive may
contain another transition candidate. C18 **does not consume it recursively**.
The caller regains control and must explicitly invoke another step.

## Interrupt behavior

`interrupt_requested_after_cycle=true` is passed only to the final C17 planning
step.

That means the current committed cycle is allowed to finish, but C17 returns an
`INTERRUPTED` directive and no next transition is consumed.

There is still no hidden second model call.

A later integration may add cancellation of an in-flight ThoughtEngine request,
but that requires a separately reviewed provider cancellation boundary.

## Binding checks

Before commit, C18 verifies that:

- directive action is exactly `NEXT_CYCLE`;
- transition source cycle equals directive cycle;
- transition adjudication ref equals directive adjudication ref;
- supervisor progress points at the transition's next cycle;
- next workspace carries the exact next cycle ID;
- next SelfState points at the exact next workspace;
- the C17 transition does not already claim persistence/model execution.

After commit, C18 verifies that the commit receipt matches the exact transition.

After cognition, it verifies that C15 ran the exact next cycle and that its
SelfState ref equals the committed SelfState ref.

## Authority

C18 itself owns no external action authority.

Its receipt pins:

```text
model_invocations=1
adjudications=1
supervisor_plans=1
state_committed_before_cognition=true
recursive_loop=false
execution_authority=false
scheduling_authority=false
durable_memory_write_authority=false
body_actuation_authority=false
voice_actuation_authority=false
production_activation=false
```

The only durable authority used by C18 is the explicitly injected state committer.

## Failure after commit

Commit intentionally happens before cognition so that a model can never reason as
though a new SelfState were current when persistence still says otherwise.

This creates an important crash boundary:

> If cognition fails after a successful commit, the new SelfState remains
> committed and C18 does not attempt an unsafe rollback.

Recovery from a post-commit/pre-receipt failure must be provenance-based and
separately designed. A later recovery slice should detect an incomplete cycle from
the committed transition/cycle lineage rather than silently decrementing SelfState
revision.

## Still not production integration

C18 is composition logic only. It adds:

- no public API route;
- no scheduler;
- no thread/background task;
- no automatic retry;
- no Agent 3/tool call;
- no Memory 4 write;
- no BodyRig/VoiceRig actuation;
- no production state committer.

`production_activation=false`.
