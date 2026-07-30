# T-022 append-only write-pilot evidence

**Status:** dormant evidence harness. It prepares and validates the physical
`note_append` pilot; it does not execute a run, expose another write tool, merge a
candidate or activate production routing.

## What this closes

The device-bound one-use approval already exists. T-022 still needs evidence that
20 physical approvals produced exactly 20 append blocks and that denial, expiry,
changed terms, replay, concurrency and stop/retry/replan failed as designed.

`scripts/agent3_write_pilot_report.py` makes that evidence candidate-bound and
forensic instead of presence-based:

- an exact manifest is minted **before** the pilot;
- 20 unpredictable marker strings are bound to 20 run IDs;
- every successful run must contain exactly one local, non-idempotent
  `note_append` step;
- the run ledger must contain the ordered confirmation/approval/execution chain;
- `approval_consumed` must agree with the durable approval-use row on device,
  revision and action/nonce/token hashes;
- ToolGate must contain exactly one `executed` audit row for the exact marker;
- `notes.md` must contain every positive marker exactly once;
- every Agent 3 run using the pilot prefix is inventoried, so an unlisted retry or
  replan cannot hide beside the 20 declared runs;
- seven negative cases are required, and denial/expiry are independently checked
  against the run ledger;
- the manifest and report bind version, exact Git SHA, worker code fingerprint and
  the SHA-256 of an eligible physical rig-validation report;
- SQLite databases are copied with SQLite's backup API before reading or hashing,
  so WAL state is included in one consistent image per store.

A green JSON report is evidence about one candidate. It still does not prove that
someone looked at a screen; the physical procedure and operator remain part of
the evidence chain.

## Preconditions

Use a frozen, exact candidate with:

- consistent version stamps;
- a clean Git working tree, or a valid gitless frozen-candidate attestation;
- a fresh Agent 3 rig-validation report whose gate says
  `eligible_for_write_pilot=true`;
- the same `KALIV_AGENT3_APPROVAL_SECRET` in backend and worker;
- `KALIV_AGENT3_APPROVAL_REQUIRED=1` during the pilot;
- only `note_append` enabled for the write-pilot ceremony.

Do not run the pilot against a moving branch. Any candidate identity drift after
manifest preparation makes collection red.

## 1. Prepare the 20-run manifest

Run on the exact rig checkout before the first preview:

```powershell
python scripts\agent3_write_pilot_report.py prepare `
  --operator Anders `
  --rig-validation validation\agent3-rig-validation-latest.json `
  --manifest validation\agent3-write-pilot-manifest.json
```

The manifest contains 20 unique texts such as:

```text
KALIV-T022:<pilot-id>:P:01:<random-marker>
```

Use each entry's `marker` as the **complete** `note_append.text` value. Do not add
prose before or after it.

## 2. Preview, confirm and bind each physical run

For each ordinal 1–20:

1. request a server-authored preview containing exactly one `note_append` step;
2. verify the visible target, append-only consequence and exact marker;
3. explicitly approve from the paired device;
4. wait for the run to reach `completed`;
5. bind the returned run ID:

```powershell
python scripts\agent3_write_pilot_report.py bind `
  --manifest validation\agent3-write-pilot-manifest.json `
  --ordinal 1 `
  --run-id <RUN-ID>
```

`bind` is single-use per ordinal and rejects duplicate or path-like IDs. It never
changes a marker or candidate binding.

## 3. Record the seven negative cases

Do not hand-write the negative JSON. Initialize the append-only, hash-chained
SQLite journal while the manifest is still unchanged:

```powershell
python scripts\agent3_write_pilot_recorder.py init `
  --manifest validation\agent3-write-pilot-manifest.json `
  --journal validation\agent3-write-pilot-negative-journal.db
```

For each case, record the before-counts **before** sending the first request. The
command returns a case ID and the exact marker to use. `replay` and
`stop_retry_replan` must target an existing positive marker and therefore require
`--positive-ordinal`:

```powershell
python scripts\agent3_write_pilot_recorder.py begin `
  --manifest validation\agent3-write-pilot-manifest.json `
  --journal validation\agent3-write-pilot-negative-journal.db `
  --case changed_args `
  --note-count 0 `
  --approval-count 0
```

Save every exact HTTP response body to a file and append one observation per
request. The recorder stores only its SHA-256, byte count, status and run ID:

```powershell
python scripts\agent3_write_pilot_recorder.py observe `
  --journal validation\agent3-write-pilot-negative-journal.db `
  --case-id <CASE-ID> `
  --status 409 `
  --response-file validation\responses\changed-args.json `
  --run-id <RUN-ID>
```

Measure the after-counts and close the case. A case cannot finish before at least
one response is recorded, cannot be reopened and cannot be edited in place:

```powershell
python scripts\agent3_write_pilot_recorder.py finish `
  --journal validation\agent3-write-pilot-negative-journal.db `
  --case-id <CASE-ID> `
  --note-count 0 `
  --approval-count 0
```

After all seven cases are complete, compile the strict negative evidence file:

```powershell
python scripts\agent3_write_pilot_recorder.py finalize `
  --manifest validation\agent3-write-pilot-manifest.json `
  --journal validation\agent3-write-pilot-negative-journal.db `
  --output validation\agent3-write-pilot-negative.json
```

Every journal row includes the previous row hash. Finalization rejects missing or
out-of-order rows, duplicate cases, manifest drift and payload tampering. The
forensic collector requires the original journal, reconstructs the strict negative
JSON from that chain and rejects any byte-level semantic mismatch. The final chain
hash is stored in the physical report.

Exactly these seven cases are required:

| Case | Required HTTP result | Note delta | Approval-use delta |
|---|---:|---:|---:|
| `deny` | `[200]` | 0 | 0 |
| `timeout` | `[409]` | 0 | 0 |
| `changed_args` | `[409]` | 0 | 0 |
| `stale_revision` | `[409]` | 0 | 0 |
| `replay` | `[409]` | 0 | 0 |
| `concurrent_approval` | one `200`, one `409` | exactly 1 | exactly 1 |
| `stop_retry_replan` | at least three `200`/`202`/`409` observations | 0 | 0 |

Every case object has exactly these fields:

```json
{
  "name": "changed_args",
  "observed_at": "2026-07-27T12:00:00Z",
  "marker": "KALIV-T022:<pilot-id>:N:changed-args",
  "request_statuses": [409],
  "response_sha256s": ["<sha256 of exact response body>"],
  "note_count_before": 0,
  "note_count_after": 0,
  "approval_use_count_before": 0,
  "approval_use_count_after": 0,
  "run_ids": ["<run id involved in the attempt>"]
}
```

For `stop_retry_replan`, `marker` must be one of the 20 positive markers. The
collector inventories all positive-prefix runs, so a second run that attempts the
same marker is visible even if the UI transcript omits it.

The `deny` and `timeout` records are additionally proven from the run database:
there must be exactly one `confirmation_denied` or `confirmation_expired` event,
no `approval_consumed`, no `step_started`, no `step_succeeded`, no approval-use
row and no marker in `notes.md`.

For concurrent approval, the named run must independently pass the same complete
success checks as a positive run, while the note and approval-use deltas remain
exactly one.

## 4. Collect the report

Run only after the worker is idle and all 20 positive runs and negative cases are
finished:

```powershell
python scripts\agent3_write_pilot_report.py collect `
  --manifest validation\agent3-write-pilot-manifest.json `
  --negative validation\agent3-write-pilot-negative.json `
  --negative-journal validation\agent3-write-pilot-negative-journal.db `
  --rig-validation validation\agent3-rig-validation-latest.json `
  --agent-db <path-to-kaliv-agent3.db> `
  --approval-db <path-to-kaliv-agent3-approvals.db> `
  --audit-db <path-to-kaliv-audit.db> `
  --notes <KALIV_TOOLS_DIR>\notes.md `
  --report validation\agent3-write-pilot-latest.json
```

Exit `0` means all checks are green. Exit `1` writes a red report with explicit
blockers. Exit `2` means evidence could not be safely read or the candidate/
rig-validation prerequisite failed.

The pilot window may span at most 12 hours, and the newest observation may be at
most 24 hours old. A fresh half cannot carry an old half.

## Report boundary

The report schema is `kaliv-agent3-write-pilot/v1`. It contains:

- exact candidate identity and evidence-file/database snapshot hashes;
- the final append-only negative-journal chain hash;
- the 20 run IDs, step IDs, marker hashes, revisions and approval times;
- the seven negative cases with response hashes and run IDs;
- one attributed device ID across the 20 positive approvals;
- window start/end and every blocking reason;
- `production_activation=false` unconditionally.

The report intentionally stores marker hashes rather than raw marker text. The
actual note comparison is performed during collection from the manifest and
`notes.md`.

## What remains physical

This harness can be fully tested in CI, but CI cannot supply:

- a real paired device approval;
- the actual Windows notes file and SQLite stores from the candidate;
- the operator's visual confirmation that the preview/card showed the exact
  append-only action;
- the 20 real runs and adversarial negative requests.

T-022 remains open until those observations exist on the frozen candidate and the
resulting report is reviewed. No PR in this stack turns the write pilot on.
