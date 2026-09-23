# C30-D — Semantic attention admission into experiential episodes

Status: draft, stacked on C30-C, `production_activation=false`.

C30-D admits three already-authoritative C26 attention paths into the process-local C30 episode without granting them new authority.

## Memory 4 recall

Empty recall remains a total no-op and consumes no runtime clock sample. A first non-empty recall reuses the exact trusted ClockSample that C26-C already used to bind the privacy-safe `memory_recall` CognitionEvent.

The episode moment contains only the event source ref, temporal anchor, salience and current goal refs. Recalled text and individual Memory 4 ids are not copied.

Exact replay reuses the existing C26-C plan/clock binding and adds no episode moment.

## Embodiment

Only C26-D semantic inference kinds that already create an `embodiment_change` CognitionEvent may add an `EMBODIMENT_CHANGE` moment. Gaze/no-event inference remains a total episode no-op.

C30-D takes one event-driven trusted runtime clock sample for a candidate semantic event and publishes the prospective episode only if supervisor revision actually advances.

The embodiment proposition is not copied into the episode state.

## Prediction

Only an exact C26-B prediction mismatch that already creates `prediction_error` may add a `PREDICTION_RESOLUTION` moment. Match/partial/indeterminate outcomes add nothing.

The structured outcome proposition and event summary are not copied into the episode state.

## Idempotency

For embodiment and prediction, supervisor revision is the publication proof: a duplicate pending event that leaves revision unchanged cannot change episode state.

## Authority boundary

C30-D adds no model call, durable Memory 4 write, body mutation, SelfState-store write, scheduler, timer, execution authority or production activation.

## Qualification

Focused tests prove Memory 4 clock reuse + privacy, empty recall no-op, gaze no-op, embodiment replay idempotency, non-mismatch no-op, prediction replay idempotency, and mixed temporal ordering in one episode.

## Next slice

C30-E may define deterministic episode-boundary policy and close/open transitions around focus/goal changes while preserving bounded process-local state and avoiding model-controlled segmentation.
