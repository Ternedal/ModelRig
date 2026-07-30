# A4-09 process-local consumer single-flight

A4-09 prevents overlapping A4-08 batches for the same campaign and consumer
inside one composed process. It does not change A4-08's durable at-least-once
semantics.

## Contract

- one shared guard permits at most one active batch for a `(campaign, consumer)`
  key;
- a second overlapping call fails immediately before its handler is invoked;
- different consumers can run concurrently;
- the guard is released in `finally`, including handler and offset-write failures;
- stale or foreign flight tokens cannot release a current operation;
- sequential calls continue from A4-08's durable cursor without duplicates.

## Safety boundary

The guard is process-local and starts no thread. Every batch remains an explicit
caller action. Separate processes, separate guard instances or direct use of the
underlying A4-08 service are not coordinated. Distributed claims, crash-surviving
leases, fencing across processes and automatic background consumption remain
separate future decisions.
