# T-022 physical append-only write-pilot operator

**Status:** dormant physical operator. It prepares and records the real pilot but
cannot approve a write, invent an observation, merge a branch, publish a build or
activate production.

Start it on the Windows rig from the exact repository checkout:

```text
START_AGENT3_WRITE_PILOT_PHYSICAL.cmd
```

## What the operator automates

- checks out the exact candidate branch and verifies a clean candidate identity;
- obtains `MODELRIG_TOKEN` and `KALIV_AGENT3_APPROVAL_SECRET` through hidden input;
- derives every non-read capability from the candidate registry;
- writes an isolated pilot-only tool-state file where `note_append` is the only
  active write capability;
- starts backend/worker with approval-required enabled;
- rebuilds and installs the exact Android APK on exactly one ADB device;
- opens Android and desktop Agent 3 developer surfaces;
- prepares the 20 unpredictable positive markers;
- runs the authenticated GET-only T-022 preflight;
- guides and binds each positive run only after exact operator attestations;
- immediately verifies each positive run against the run ledger, approval-use DB,
  ToolGate audit and `notes.md`;
- initializes the append-only negative journal **after** all 20 run IDs are bound;
- guides the seven negative cases and records exact status/response hashes;
- measures note and approval-use deltas directly from durable stores;
- finalizes the negative JSON from the verified hash chain;
- runs the existing forensic collector and writes the final T-022 report.

## Fixed order

The wizard enforces this sequence:

1. exact candidate and isolated write-tool state;
2. candidate-bound rig-validation;
3. unbound 20-run manifest;
4. read-only preflight;
5. 20 positive approvals and manifest bindings;
6. negative journal initialization against the **fully bound** manifest;
7. seven negative cases;
8. forensic collection.

The journal is not initialized before step 5. Binding a run ID changes the
manifest hash, so creating the journal earlier would make the evidence chain
belong to an obsolete manifest.

## Human boundary

The wizard cannot see the confirmation card and cannot approve it. Every positive
run requires these exact phrases, including its ordinal:

```text
PREVIEW MATCHER ORDINAL <n>
APPROVAL GIVET ORDINAL <n>
RUN COMPLETED ORDINAL <n>
```

These phrases are attestations, not substitutes for durable evidence. Immediately
after the phrases, the wizard verifies that:

- the run exists and contains the exact marker;
- the complete approval/confirmation/execution event chain exists;
- one device-bound approval-use row exists;
- one executed ToolGate audit row exists;
- the marker occurs exactly once in `notes.md`.

A plain `ja`, Enter or a guessed run ID cannot close the run.

## Resume behavior

The manifest and journal are the state machines; no editable progress JSON is
trusted.

- Bound positive ordinals are skipped.
- If an append completed but the process stopped before manifest binding, the
  wizard searches the durable ledger and note for the exact marker. It only
  recovers when exactly one run is independently green, and requires:

  ```text
  RECOVERED EVIDENCE REVIEWED ORDINAL <n>
  ```

- A negative case interrupted after `begin` or one or more observations resumes
  from the same case ID and next journal sequence.
- Closed negative cases are skipped.
- A failed delta check leaves the case open; it is never rewritten or marked
  passed.

## Negative cases

Exactly these cases are required:

| Case | Required response statuses | Note delta | Approval-use delta |
|---|---|---:|---:|
| `deny` | `[200]` | 0 | 0 |
| `timeout` | `[409]` | 0 | 0 |
| `changed_args` | `[409]` | 0 | 0 |
| `stale_revision` | `[409]` | 0 | 0 |
| `replay` | `[409]` | 0 | 0 |
| `concurrent_approval` | one `200`, one `409` | 1 | 1 |
| `stop_retry_replan` | at least three of `200/202/409` | 0 | 0 |

Each case requires the exact start and finish attestations:

```text
NEGATIV CASE UDFØRT <case>
NEGATIV DELTA BEKRÆFTET <case>
```

The operator copies an exact HTTP response body or pastes it as a single line.
The append-only recorder stores its SHA-256, byte length, status and run ID. It
never edits a prior observation.

## Required local inputs

The wizard proposes the stable defaults under `%LOCALAPPDATA%\Kaliv` and
`%USERPROFILE%\Documents\Kaliv`, but shows each path before use:

- `kaliv-agent3.db`;
- `kaliv-agent3-approvals.db`;
- `kaliv-audit.db`;
- `notes.md`.

The approval secret and device token remain environment-only and are never written
to the evidence files.

## Safe stop

Ctrl+C, a wrong phrase, a mismatched delta, a stale candidate or any unreadable
store stops the process. Existing manifest, journal and response artifacts remain
for review/resume. The operator never auto-corrects evidence.

## Result boundary

A successful run writes:

```text
validation/agent3-write-pilot-latest.json
```

A green report proves the 20 positive and seven negative cases for one exact
candidate. It still does not merge, release or enable normal routing, and always
contains:

```json
"production_activation": false
```
