# Kaliv end-to-end latency qualification

`scripts/kaliv_end_to_end_latency_qualifier.py` produces the canonical evidence
for the `end_to_end_latency` Kaliv system release gate.

This is deliberately a **measurement gate**, not an invented performance SLO.
The repository does not yet have a physically established cross-rig latency
threshold, so this qualifier proves and records one real correlated traversal
without claiming that the measured value is "fast enough".

## Required event

The qualifier does **not** accept a caller-authored envelope as release
authority. It reads three concrete source receipt files from one evidence root:

1. `perception_received`
2. `cognition_completed`
3. `outward_started`

Each source receipt is bounded, regular, non-symlink UTF-8 JSON and is hashed
with SHA-256 from its exact bytes. All three receipts must bind the same
`candidate_git_sha`, `event_id`, `runtime_epoch` and `observer_id`.
The files and their byte digests must be distinct.

The perception receipt binds a concrete real input identity. The cognition
receipt must bind the canonical cognition event id, a nonblank transition
receipt and at least one completed real cycle. The outward receipt must state
`started=true` and carry the required runtime identity: `utterance_id` for
voice, `body_runtime_id` for body, or both for `voice+body`. A queued
request is not outward-start evidence.

The clock contract is exact:

```json
{
  "kind": "monotonic",
  "unit": "milliseconds",
  "origin": "single-observer"
}
```

This avoids cross-machine wall-clock skew. Timestamps must satisfy:

```text
perception_received <= cognition_completed <= outward_started
```

The qualifier derives:

- perception → cognition milliseconds;
- cognition → outward milliseconds;
- total perception → outward milliseconds.

`outward_kind` must be `voice`, `body`, or `voice+body`.

## Authority boundary

A valid verdict contains:

```json
{
  "state": "MEASURED",
  "threshold_applied": false,
  "end_to_end_latency_gate_satisfied": true,
  "release_gate_satisfied": false,
  "production_activation": false
}
```

The canonical release reference is:

```text
kaliv-end-to-end-latency:<modelrig-sha>:<sha256>
```

The system release gate accepts exactly one such reference for
`end_to_end_latency=PASS`. The embedded ModelRig SHA must equal the pinned
release SHA or be its Git ancestor with the exact same tree, permitting only a
clean merge-commit identity change.

A later physical baseline may establish an SLO. Until that happens, this
qualifier must continue to report `threshold_applied=false`; CI must not invent
or infer a threshold.

## Producing the receipts

The worker writes the receipts itself, from its own trusted clock, on two
default-off routes mounted by `KALIV_E2E_LATENCY_QUALIFICATION_ENABLED=1`. A
turn names the measurement it wants with `outward_kind`:

| `outward_kind` | Release | Ends when | Body |
|---|---|---|---|
| `voice` | Kaliv V1 (ADR-SYS-001 D5 and D6) | a client reports on `POST /experimental/e2e-latency/voice/{utterance_id}/started` that it has dispatched playback of the reply | None. No body session is created, read or required, and the receipt's `body_runtime_id` is null. |
| `voice+body` (default) | Kaliv Embodied | the client reports `POST /body/speech/{utterance_id}/started` | An active body is required, and the receipt names its runtime. |

A playback start is reported once. A second report is refused and does not move
the timestamp. The reporter supplies only the utterance; candidate, event and
observer identity are the worker's own.

### The Kaliv V1 voice measurement on the rig

> **Not yet run on the rig.** The routes and the driver are covered by tests
> against fakes on Linux. Microphone recording and `winsound` playback are
> Windows-only code that no test executes.

`scripts/kaliv_e2e_latency_voice_driver.py` is the client: it takes one spoken
utterance, posts it, hands the reply to the player on the rig, and only then
reports the start.

Start the worker from the clean candidate checkout with the Consciousness
flags and profile of
[`consciousness-core/LIVE_CYCLE_QUALIFICATION.md`](consciousness-core/LIVE_CYCLE_QUALIFICATION.md)
(the route needs the live cognitive session, speech recognition and speech
synthesis), plus:

```powershell
$env:KALIV_E2E_LATENCY_QUALIFICATION_ENABLED = "1"
$env:KALIV_E2E_LATENCY_CANDIDATE_GIT_SHA = (git rev-parse HEAD)
$env:KALIV_E2E_LATENCY_EVIDENCE_ROOT = (Join-Path (Get-Location) "validation\e2e-latency")
```

Then, in another window in the same checkout:

```powershell
python scripts\kaliv_e2e_latency_voice_driver.py --record-seconds 5
```

Speak when it says so. It prints the run record and the exact qualifier command
for the three receipts.

If recording from the microphone fails, record a WAV with any tool and pass it
within ten minutes. A recording is accepted once:

```powershell
python scripts\kaliv_e2e_latency_voice_driver.py --wav C:\path\to\utterance.wav
```

If the reply cannot be played through `winsound`, name a player. The start is
reported when the player has been launched:

```powershell
python scripts\kaliv_e2e_latency_voice_driver.py --record-seconds 5 --player-command "ffplay -nodisp -autoexit {wav}"
```

### What this number is

**The metric is: from the worker accepting the audio to playback of the reply
being dispatched on the rig.** Use that wording in a release claim. It is not a
verified first audible reply, and it is not the latency a phone user
experiences.

The clock starts when the worker has accepted the audio. It stops when the
client reports on the worker's loopback that it has handed the reply to the
player. It therefore does **not** include:

- capturing the utterance and getting it to the worker;
- the network between a phone and the rig;
- playback on a phone;
- the output latency of the playback device;
- the time from dispatch until the reply became audible. Neither the worker
  nor the driver listens.

### What the receipts assert, and what stands behind it

All three receipts carry `real_event: true`, `simulated: false` and
`replay: false`. **The worker sets those three values on every turn of this
route.** They are the route's assertion. They are not findings about the audio.

The route receives audio bytes and cannot tell an utterance spoken now from a
recording. **Nothing in this evidence proves that the utterance was spoken
live.** What stands behind `replay: false` is:

- **The operator's attestation.** Whoever runs the driver attests that the
  utterance was spoken for this turn.
- **Two mechanical checks in the driver.** A supplied WAV must be at most ten
  minutes old, and a recording is accepted once. They narrow the room for a
  mistake. They prove nothing about how the audio was made.

The run record names where the audio came from:

| `input.source` | Meaning |
|---|---|
| `recorded_by_driver` | The driver recorded it from the default input device, directly before posting. |
| `operator_supplied_wav` | The operator passed a file with `--wav`. |

Both carry `live_utterance_verified: false`. The source follows from which
input was given; no option sets it.

### The two sidecar files

The receipt's schema is exact and has no field for any of this, so it is
written beside the receipts:

| File | Written by | Holds |
|---|---|---|
| `voice_outward_scope.json` | the worker | what the stamp is (`outward_event`), `audible_onset_measured: false`, `live_utterance_verified: false`, the asserted receipt fields, and `not_measured` |
| `rig_driver_run.json` | the driver | the source of the utterance, the player, `start_event: dispatch`, the same `not_measured` list, and the SHA-256 of the input, the reply, the three receipts and `voice_outward_scope.json` |

The driver refuses to write its record if the worker's sidecar is missing or
says less than this.

**The gate sees only the `kaliv-end-to-end-latency:` reference. It cannot
certify any of the above.** Whoever reviews that reference for a release must
open both files. Checklist:

1. The three receipt hashes in `rig_driver_run.json` match the receipt files.
2. `scope_sidecar.sha256` matches `voice_outward_scope.json`.
3. `input.source` is read and accepted for this release.
4. `playback.start_event` is `dispatch`, and the release claim uses the wording
   at the top of this section.
5. Both `not_measured` lists hold the same six lines: the five above, and that
   the route cannot tell whether the utterance was spoken live.

Keep both files with the receipts.

## Run

Store all three receipts below one evidence directory and invoke the qualifier
with explicit paths:

```powershell
python scripts/kaliv_end_to_end_latency_qualifier.py `
  --evidence-root .\validation\latency-event-001 `
  --perception perception_received.json `
  --cognition cognition_completed.json `
  --outward outward_started.json `
  --report .\validation\kaliv-end-to-end-latency-latest.json
```

A successful run exits 0 and emits a content-addressed
`release_evidence_ref` plus the relative path and SHA-256 of every validated
source receipt. Missing/unreadable/oversized/path-escaped/symlinked receipts,
hash-content substitution via reused receipt bytes, mixed candidate/event/
runtime-epoch/observer identity, replay/simulation, incomplete cognition,
queued-but-not-started outward behavior, non-monotone timing, or authority
overclaim exits 2.

Legacy hand-authored v1 latency envelopes are intentionally no longer accepted
as release evidence.
