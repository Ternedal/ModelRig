# Scheduler pilot evidence — T-019

**Status: read-only collector and evidence schema. The physical pilot itself must run on ModelRig.**

`scripts/scheduler_pilot_evidence.py` does not create, approve, enable, revoke or
execute a schedule. It reads the existing runtime identities and SQLite truth
after the bounded pilot described in `DEVICE_TEST.md`, then writes one redacted,
candidate-bound report.

## What the report proves

The manifest names exact schedule and occurrence ids. The collector cross-checks:

- the clean checkout's VERSION, Git SHA and worker code fingerprint;
- the running backend version and worker code fingerprint;
- Scheduler configured, running and without a runtime error;
- one read schedule with no approval fingerprint or receipt;
- one `note_append` schedule with the exact args hash, approval receipt and paired-device attribution;
- one executed audit row and one terminal job for every named executed occurrence;
- the unique note marker occurs exactly once per named write claim;
- a revoked occurrence is released, terminal and has no executed audit;
- exactly one blocked audit exists for the revoked schedule inside the pilot
  window; current runtime records blocked audit at schedule scope, so the report
  explicitly states `claim_bound=false` rather than pretending claim-level binding;
- a recovered occurrence is exactly `executed` or `abandoned` as declared;
- all named pilot occurrences are terminal and no pilot schedule remains reserved;
- `production_activation=false` regardless of outcome.

The report excludes:

- `MODELRIG_TOKEN`;
- raw schedule arguments;
- the note marker text;
- full tool results and job details;
- receipt nonces (only their SHA-256 is stored);
- absolute database and note paths.

## 1. Run the bounded pilot

Use the current physical candidate and follow the Scheduler section in
`DEVICE_TEST.md`. Keep budgets small:

- read path: `rig_status`, for example two runs;
- write path: `note_append`, exactly one run with a unique marker;
- revoke path: pause/revoke after claim but before ToolGate;
- recovery path: create a controlled interrupted claim and record whether the
  expected outcome is `executed` or `abandoned`.

Do not reuse a marker from an earlier test. The marker's uniqueness is how the
collector detects a duplicate append.

## 2. Inventory ids without exposing args

From the repository root on the rig:

```powershell
python scripts\scheduler_pilot_evidence.py --inventory |
  Set-Content -Encoding utf8 validation\scheduler-pilot-inventory.json
```

The inventory contains only schedule ids, tool names, cadence/budget state and
occurrence/job ids/statuses. It intentionally excludes args, receipts, audit
summaries and note contents.

## 3. Prepare the exact manifest

```powershell
Copy-Item `
  eval\scheduler_pilot_manifest.example.json `
  eval\scheduler_pilot_manifest.json
```

Fill in:

- candidate VERSION, `git rev-parse HEAD` and worker code fingerprint;
- the UTC pilot start/end timestamps with offsets; every named schedule, claim,
  job, audit execution and write receipt must fall inside this window;
- exact schedule and claim ids from the inventory;
- read/write cadence and max-runs used in the pilot;
- SHA-256 of the canonical args JSON;
- SHA-256 of the trimmed unique note marker;
- the paired-device id shown by the consumed approval receipt;
- recovery's expected terminal status: `executed` or `abandoned`.

The declared pilot window must be no longer than 12 hours, may not finish more
than five minutes in the future, and must have finished within the last 24 hours.
Those bounds prevent a manifest from sweeping old database rows into a new pilot.

For the empty read args object `{}`, the canonical args hash is already present in
the example manifest.

A convenient PowerShell calculation for the marker is:

```powershell
$marker = 'YOUR-UNIQUE-PILOT-MARKER'
$bytes = [Text.Encoding]::UTF8.GetBytes($marker.Trim())
$sha = [Security.Cryptography.SHA256]::Create()
([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
```

The args hash must be calculated over compact JSON with object keys sorted. For
`note_append`, the canonical object has the shape `{"text":"..."}`.

The working manifest is git-ignored because it contains local ids and device
attribution.

## 4. Collect the candidate-bound report

Keep the paired token only in the environment:

```powershell
$env:MODELRIG_TOKEN = '<paired-device-token>'
python scripts\scheduler_pilot_evidence.py `
  --manifest eval\scheduler_pilot_manifest.json `
  --report validation\scheduler-pilot-latest.json
```

The collector accepts only loopback backend/worker URLs. It opens all three SQLite
databases in URI `mode=ro` with `PRAGMA query_only=ON`.

Expected final line:

```text
PASS: candidate-bound scheduler pilot evidence
```

A passing report has:

```json
{
  "schema": "kaliv-scheduler-pilot-evidence/v1",
  "gate": {
    "passed": true,
    "physical_scheduler_pilot_complete": true,
    "production_activation": false
  }
}
```

## 5. Review and preserve evidence

Review the rolling report before copying it:

```powershell
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
Copy-Item `
  validation\scheduler-pilot-latest.json `
  "validation\scheduler-pilot-$stamp.json"
```

Confirm that:

- candidate and runtime identities match and `worker_frozen=true`;
- every evidence timestamp falls within the declared pilot window;
- read has zero receipts;
- write has one receipt from the expected device;
- each pilot trial uses a distinct schedule and its complete occurrence set
  matches the manifest exactly;
- every named claim has one terminal occurrence and a job status consistent with
  the occurrence outcome;
- each executed claim has exactly one matching audit execution and args hash;
- marker count equals write claim count;
- revoke and recovery match their declared outcomes;
- no local absolute path, raw marker, args or token appears;
- `physical_scheduler_pilot_complete=true` and `production_activation=false`.

Only a dated, manually reviewed report may be committed. The rolling report,
inventory and filled manifest remain local.
