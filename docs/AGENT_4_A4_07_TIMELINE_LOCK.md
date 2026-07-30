# A4-07 — Cross-process timeline writer lock

## Purpose

A4-06 protects one process with an in-memory `RLock`, but two independent
processes can otherwise read the same last timeline entry and append competing
next entries. A4-07 adds an explicit operating-system writer lock per campaign.

## Contract

`FileCampaignTimelineLockManager` creates a separate one-byte lock file whose
name is bound to the campaign id by SHA-256. Acquisition uses an advisory,
exclusive, non-blocking operating-system lock with a bounded polling deadline.

- POSIX uses `fcntl.flock`.
- Windows uses `msvcrt.locking`.
- The descriptor remains open for the complete critical section.
- Releasing is idempotent.
- Process termination closes the descriptor and releases the operating-system
  lock; no stale TTL record needs to be reclaimed.
- Different campaigns use different lock files and may proceed independently.

`ProcessSafeCampaignTimeline` composes this lock with the A4-06 JSONL store. It
holds the campaign lock across read/verify/append, releases it before local
callbacks, and preserves durable-before-callback delivery.

## Safety boundary

- caller-driven only;
- no background thread, daemon, timer, mount or automatic retry;
- lock acquisition has a finite timeout and fails closed;
- construction creates no directory or file;
- lock files contain no campaign content or credentials;
- no distributed/network filesystem fencing claim is made;
- no deletion, pruning, compaction, encryption or artifact upload is added;
- the underlying A4-06 hash-chain and evidence contracts remain unchanged.

## Validation

The A4-07 test gate covers:

1. dormant construction;
2. same-campaign exclusion and bounded timeout;
3. idempotent release and reacquisition;
4. independent locks for different campaigns;
5. serialization across two timeline-store instances;
6. durable-before-callback behavior and lock release after handler failure;
7. fail-closed timing configuration.
