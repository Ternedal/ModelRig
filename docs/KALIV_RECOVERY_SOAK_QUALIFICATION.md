# Kaliv recovery-soak qualification

`scripts/kaliv_recovery_soak_qualification.py` produces the canonical evidence
for the `recovery_soak` Kaliv system release gate. It validates an observations
file. `scripts/kaliv_recovery_soak_collector.py` produces that file from the
running appliance.

Neither script starts, stops, restarts, updates or activates anything. The
collector sends GET requests to loopback only and reads one file, the
supervisor heartbeat.

> **Not yet run on the rig.** The collector is covered by its contract test
> against a fake appliance on Linux. Its first run on Windows is a test of the
> tool as much as of the appliance.

## What the gate requires

The qualifier accepts an observations file (`kaliv-recovery-soak-observations/v1`)
only when all of the following hold:

- every sample reports `backend_healthy`, `worker_healthy`, `supervisor_looping`
  and `state_error_absent` as true;
- the samples span at least `policy.required_duration_seconds`, with no two
  consecutive samples further apart than `policy.max_sample_gap_seconds`;
- the four recovery events (`reboot`, `backend_restart`, `worker_restart`,
  `interruption_recovery`) carry exactly the evidence reference and timestamp of
  the Stage-B report's hash-bound lifecycle artefacts, and every one of them
  lies **inside** the sample window;
- the Stage-B final report is complete, re-validates, and names the checkout's
  own candidate.

The last-but-one point decides the order of work: **sampling has to begin
before Stage B's first trial and run through all of them.** A soak started
after Stage B cannot pass, because the recovery events would lie before its
first sample.

The policy is declared by the operator. The qualifier enforces whatever
duration and gap the file declares; it does not set them. The values in
`eval/recovery_soak_observations.example.json` are six hours and fifteen
minutes.

## What a probe records

| Field | True when |
|---|---|
| `backend_healthy` | `GET <backend>/healthz` answers 200 with `status` = `ok`. |
| `worker_healthy` | `GET <worker>/healthz` answers 200 with `status` = `ok`, and `GET <worker>/health/full` reports `ok` = true. |
| `supervisor_looping` | The supervisor heartbeat file advances while the probe watches it. A file that exists but stands still is a dead supervisor. |
| `state_error_absent` | `/health/full` reports `checks.tools.ok` = true, which is the tool gate's `state_error is None`. |

Anything the probe cannot determine is recorded as false. Each probe also
records the backend and worker versions and the worker's commit, for the
assembly record.

Every probe is appended to an append-only journal and forced to disk, red or
green. The journal is never rewritten.

## Red probes

Stage B takes the appliance down on purpose: the interrupted update, the good
update, the reboot and the two supervisor restarts. A probe that lands in that
downtime is red, and a red probe cannot be a sample.

`assemble` leaves a red probe out of the observations only when it lies inside
the period Stage B's own four recovery timestamps bound, widened by a declared
tolerance. The tolerance may not exceed the policy's `max_sample_gap_seconds`
and defaults to it. **A red probe anywhere else fails the assembly, and no file
is written.**

A journal line that cannot be read as a probe (a torn write) is treated as a
red probe taken some time between its readable neighbours.

From the reboot onwards every sample must report the Stage-B candidate's
version, so a soak cannot continue unnoticed on another release.

What was left out is listed in the assembly record
(`validation/recovery-soak-assembly.json`) with the journal's SHA-256. The
qualifier reads only the observations file and does not see the red probes, so
the record and the journal are what a reviewer checks the exclusion against.

## Run

All paths are relative to the candidate checkout. The journal, the observations
file and the record must lie below `validation/`: untracked files there are the
only local output the freeze gate accepts in a candidate checkout.

### 1. Start sampling, before Stage B

In a separate window, from the candidate checkout:

```powershell
python scripts\kaliv_recovery_soak_collector.py sample
```

It probes every five minutes and prints one line per probe. The heartbeat is
read from `C:\Rig\ModelRig\logs\supervisor-heartbeat`; pass `--heartbeat` if the
appliance lives elsewhere.

The loop does not survive the Stage-B reboot. Either start it again within the
policy's gap after logging in, or let Windows run single probes instead:

```powershell
schtasks /Create /F /TN KalivSoakProbe /SC MINUTE /MO 5 /TR "cmd /c cd /d C:\Users\admin\Desktop\ModelRig-git && python scripts\kaliv_recovery_soak_collector.py sample --once"
```

Remove the task when the soak is over:

```powershell
schtasks /Delete /F /TN KalivSoakProbe
```

### 2. Run Stage B

As the Stage-B runbook describes. Leave the appliance running afterwards.

### 3. Watch the window

```powershell
python scripts\kaliv_recovery_soak_collector.py status --required-duration-seconds 21600
```

`seconds_remaining` reaches 0 when the window is long enough. `red` lists every
red probe.

### 4. Assemble and qualify

`assemble` re-runs the qualifier's Stage-B validation, which includes the
freeze check. Set `GITHUB_TOKEN` first, as for the freeze check itself.

```powershell
python scripts\kaliv_recovery_soak_collector.py assemble `
  --stage-b-report validation\stage-b-physical-final-latest.json `
  --required-duration-seconds 21600 `
  --max-sample-gap-seconds 900

python scripts\kaliv_recovery_soak_qualification.py `
  validation\recovery-soak-observations.json `
  --stage-b-report validation\stage-b-physical-final-latest.json `
  --report validation\kaliv-recovery-soak-latest.json
```

`assemble` hands the exact bytes it is about to write to the qualifier and
writes nothing if the qualifier refuses them. The second command is the
qualification; its `release_evidence_ref` is the reference for the release
manifest:

```text
kaliv-recovery-soak:<modelrig-sha>:<sha256>
```

If the appliance was used or stopped after the soak, bound the window so later
probes are not part of the claim:

```powershell
  --window-end 2026-01-01T18:00:00+00:00
```

`--window-start` does the same at the other end. Probes outside a declared
window are counted in the record and are not part of the observations.

## Authority boundary

A qualified verdict means the declared policy held over the sampled window on
the Stage-B candidate. It does not prove any other release gate, and it keeps
`production_activation` false.

The collector's journal is written by the operator's own machine. Nothing in it
is signed. It is evidence in the same sense as the other files under
`validation/`: bound by hash into the record, and only as trustworthy as the
checkout it was collected in.
