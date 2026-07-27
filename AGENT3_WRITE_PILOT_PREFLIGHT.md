# T-022 write-pilot preflight

**Status:** dormant, read-only operator gate. This command does not preview,
approve, start, retry, cancel or replan an Agent 3 run. It only reads live
status plus local evidence stores and writes its own JSON report.

Run it **after** `agent3_write_pilot_report.py prepare` and **before** the first
physical preview.

## What it blocks

The preflight exits red when any of these are true:

- the 20-run manifest is malformed, stale, already partly bound or belongs to
  another version, Git SHA, worker code fingerprint or identity source;
- the physical rig-validation report changed after manifest preparation or is
  no longer eligible for the write pilot;
- the running worker reports another version/code/report;
- `KALIV_AGENT3_APPROVAL_REQUIRED` is not live;
- Agent 3 or the production-tool-path safety invariant is not in the expected
  dormant state;
- the tool layer is off, `note_append` is not the exact local non-idempotent
  write capability, or another write/admin/destructive tool is enabled;
- the supplied notes path differs from the worker's live `tools_dir`;
- the notes file, Agent 3 run ledger or ToolGate audit already contains the
  prepared pilot prefix;
- another Agent 3 run is still running or waiting for confirmation;
- the notes target or future negative-journal directory is not writable;
- the negative evidence journal path already exists.

SQLite files are copied with SQLite's backup API before inspection, so WAL state
is included in each baseline hash. The command performs only authenticated GETs:

- `GET /api/v1/experimental/agent3/status`
- `GET /api/v1/tools`

## Run on the exact rig candidate

Keep the paired-device token in the environment, not in shell history:

```powershell
$env:MODELRIG_TOKEN = "<paired-device-token>"
```

Then run:

```powershell
python scripts\agent3_write_pilot_preflight.py `
  --manifest validation\agent3-write-pilot-manifest.json `
  --rig-validation validation\agent3-rig-validation-latest.json `
  --agent-db <path-to-kaliv-agent3.db> `
  --approval-db <path-to-kaliv-agent3-approvals.db> `
  --audit-db <path-to-kaliv-audit.db> `
  --notes <KALIV_TOOLS_DIR>\notes.md `
  --negative-journal validation\agent3-write-pilot-negative-journal.db `
  --report validation\agent3-write-pilot-preflight.json
```

Use `--base-url` only when the backend is not at
`http://127.0.0.1:8080`; `MODELRIG_BASE_URL` is also accepted.

## Verdict

- exit `0`: green; the prepared manifest is clean and the live rig matches it;
- exit `1`: red report with explicit blockers;
- exit `2`: an input, database, notes file or live status could not be read
  safely.

The report schema is `kaliv-agent3-write-pilot-preflight/v1`. It records exact
candidate identity, manifest/report/live-response hashes, transactionally
consistent database snapshot hashes, baseline row counts and every blocker.
It always contains `production_activation=false`.

A green preflight is not physical write evidence. T-022 remains open until the
20 paired-device approvals and seven adversarial cases have been run and the
forensic collector is green on the same frozen candidate.
