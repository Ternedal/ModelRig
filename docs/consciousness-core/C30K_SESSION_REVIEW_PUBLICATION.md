# C30-K — Non-blocking C19 review publication

Status: draft, stacked on C30-J, `production_activation=false`.

C30-K connects C30-H closure evidence to the optional C30-J review mailbox
without making episode segmentation depend on review infrastructure.

## Core invariant

> Episode boundary application wins. Review publication is advisory.

C19 applies the C30-F/G boundary first, updates the active episode and boundary
receipt, and only then attempts review publication.

A missing, full, closed or replay-rejecting mailbox cannot undo or block the
episode boundary result.

## Publication receipt

`EpisodeReviewPublicationReceipt` records one of:

- `NOT_APPLICABLE` — no closure happened;
- `MAILBOX_UNAVAILABLE` — no mailbox was injected;
- `NO_REVIEW` — the closed episode had no moments;
- `ENQUEUED` — request admitted;
- `DUPLICATE`;
- `CAPACITY_REACHED`;
- `MAILBOX_CLOSED`;
- `REPLAY_LEDGER_FULL`.

Every status carries `boundary_result_preserved=true` and
`retry_scheduled=false`.

## Explicit opt-in C19 wiring

`ProductionCognitiveSession` accepts an optional
`EpisodeExperienceReviewMailbox`.

The default remains `None`. The production session factory does not create or
enable a mailbox automatically in this slice.

When injected, C19 exposes only a read-only mailbox snapshot and the latest
publication receipt.

## Lifecycle

The injected mailbox is owned by that C19 session binding. Session close clears
and closes the mailbox, preventing review evidence from leaking across process
or session lifecycle boundaries.

## No hidden reliability system

Publication failures are visible receipts only.

C30-K creates no retry queue, timer, scheduler, background task, durable
outbox, Memory 4 write or model call.

## Qualification

Focused tests prove:

- no-op publication without closure evidence;
- absent mailbox is advisory only;
- empty episodes are suppressed;
- successful enqueue and duplicate classification;
- closed mailbox classification;
- C19 rotation occurs before successful publication;
- a full mailbox cannot block a subsequent episode rotation;
- C19 without a mailbox behaves normally;
- session close clears the injected mailbox.

## Next slice

C30-L may expose a bounded read/consume surface for a trusted UI/operator review
adapter without adding a public unauthenticated route or durable review queue.
