# Agent 4 A4-09 — explicit dormant runtime composition

A4-09 defines one canonical single-process composition of the active B-reference
architecture. The factory wires existing Agent 4 services but does not mount a
runtime, create filesystem state or start work.

## Object graph

`compose_agent4_runtime(...)` creates one shared graph containing:

- the JSON campaign repository and immutable checkpoint store;
- the append-only `JsonCampaignTimelineStore`;
- one `TimelineCampaignEventRecorder` used by lifecycle, checkpoint, failure and
  health-intervention services;
- the shared campaign queue and process-local resource lease manager;
- the resource-aware lifecycle service;
- checkpoint, retry-planning and failure-handling services;
- the caller-created health-intervention boundary;
- one durable timeline cursor store;
- caller-driven delivery, shared process-local single-flight, bounded batches and
  verified query paging.

Timeline storage does not import or contain event-bus behavior. The composition
connects lifecycle writes directly to the timeline recorder, preserving
ADR-A4-002's dependency direction.

## Explicit operations

Composition itself performs no recovery or action. A host must explicitly call:

- lifecycle methods such as `submit()` and `dispatch_ready()`;
- `Agent4RuntimeContext.recover()` for startup recovery;
- `Agent4RuntimeContext.health_intervention()` to create a coordinator;
- delivery, batch or query methods on the exposed caller-driven services.

## Filesystem paths

`Agent4RuntimePaths` reserves deterministic locations under one root:

- `campaigns/`;
- `checkpoints/`;
- `timeline/`;
- `delivery-cursors/`.

Constructing the paths and stores creates none of these directories. Filesystem
state appears only after an explicit write operation.

## Safety boundary

- no HTTP/API route, socket, authentication choice or network request;
- no automatic recovery, dispatch, checkpoint, retry or health intervention;
- no background thread, timer, polling loop, tailer or refresh;
- no module-level runtime singleton;
- no event-bus subscription or transient dual-write;
- no Agent 3 contract change or production activation.

## Validation

The existing Agent 4 workflow root verifies:

- dormant construction and shared-object identity;
- lifecycle, checkpoint, query and batch operations over one timeline;
- failure handling through the shared queue and resource release;
- restart without implicit recovery, then explicit recovery and sequence
  continuation;
- explicitly created health-intervention execution;
- invalid boundaries before filesystem activation;
- public package exports for the context, paths and factory.
